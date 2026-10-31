"""Export stored life-science positions; optionally collect current public sources.

No subscriber state, Telegram credentials or messages are used. Discovery keeps
the collector's existing source/detail budgets and qualification rules. A report
beside the CSV distinguishes an empty result from unavailable sources.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COLUMNS = ('title', 'institution', 'country', 'location', 'position_type',
           'research_fields', 'deadline', 'deadline_note', 'salary', 'funding_status',
           'research_priority', 'application_url', 'source', 'first_seen_at',
           'last_seen_at', 'availability')

# Exact employer identities audited on 2026-10-31. Historical journal rows
# retained these API index dates before the employer instructions were reviewed.
# Redact only the old unverified cutoff claim in presentation, never history.
_BERN_JOBS = "https://jobs.unibe.ch/job-vacancies/"
_REVIEWED_BERN_INDEX_ENDS = {
    (
        _BERN_JOBS
        + "phd-student-in-cancer-immunology-and-leukemia-stem-cell-biology/"
        + "0a6853ac-d531-4ac1-bc57-592090585e19"
    ): (
        "2026-11-27", "Unverified index end date; employer advert states no cutoff",
    ),
    (
        _BERN_JOBS
        + "phd-position-nccr-genesis-combining-remote-and-in-situ-life-detection-techniques/"
        + "7e52c2be-b908-4dfd-b634-c72519d07262"
    ): (
        "2026-12-31", "Rolling until filled; not a confirmed hard deadline",
    ),
}


def stored_positions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError('Position journal contains a non-object record')
    from predoc_pipeline.ingest.life_sciences import historical_life_title_disqualified

    return [
        row for row in rows
        if row.get('category') == 'life_sciences_phd'
        and not historical_life_title_disqualified(
            str(row.get('title') or ''), str(row.get('url') or '')
        )
    ]


def write_csv(path: Path, positions: list[dict[str, Any]]) -> int:
    """Keep known facts, preserve historical rows, and escape spreadsheet formulas."""
    from predoc_pipeline.boards.utils.geo import detect_location

    unique: dict[str, dict[str, Any]] = {}
    for item in positions:
        url = str(item.get('url') or item.get('application_url') or '')
        if not url:
            raise ValueError('Position has no application URL')
        original = unique.get(url)
        if original is None:
            unique[url] = dict(item)
            continue
        # Historical rows arrive before fresh discovery. A first-wins dedupe
        # silently discards updated deadlines and workplaces from the actual
        # employer advert. Combine evidence without erasing known old fields.
        updated = dict(original)
        updated.update({
            name: value for name, value in item.items()
            if value is not None and value != ''
        })
        if original.get('first_seen_at'):
            updated['first_seen_at'] = original['first_seen_at']
        # A fresh fetch alone does not verify that a previously closed advert
        # reopened or that funding status has independently been established.
        if (original.get('availability') == 'closed'
                and item.get('availability') in (None, '', 'unknown')):
            updated['availability'] = 'closed'
        if (original.get('funding_status') == 'verified'
                and item.get('funding_status') in (None, '', 'unverified')):
            updated['funding_status'] = 'verified'
        unique[url] = updated
    aliases = {'institution': 'employer', 'application_url': 'url',
               'position_type': 'category'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for item in sorted(unique.values(), key=lambda row: str(row.get('title', '')).casefold()):
            # Older Bern exports were stamped with unverified Prospective
            # index end dates. Correct the view only where the precise old
            # date and metadata are still present; verified future revisions
            # and historical journal bytes remain untouched.
            audited = (
                _REVIEWED_BERN_INDEX_ENDS.get(str(item.get('url') or ''))
                if item.get('source') == 'life_dach_bern' else None
            )
            stale_bern_end = bool(
                audited is not None
                and str(item.get('deadline') or '') == audited[0]
                and str(item.get('deadline_note') or '').startswith(
                    'Official UniBE posting ends'
                )
            )
            row = {}
            for column in COLUMNS:
                value = str(item.get(column, item.get(aliases.get(column, column), '')) or '')
                if stale_bern_end and column == 'deadline':
                    value = ''
                elif stale_bern_end and column == 'deadline_note' and audited is not None:
                    value = audited[1]
                if column == 'availability' and not value:
                    value = 'unknown'
                if column == 'country' and not value:
                    # Legacy journal rows retained location but omitted country.
                    # Recover only an identifiable country; never infer one
                    # from the employer or the job-board host.
                    inferred, _ = detect_location(item.get('location'))
                    value = inferred if inferred not in (None, 'Europe', 'Other') else ''
                if value.lstrip().startswith(('=', '+', '-', '@')):
                    value = "'" + value
                row[column] = value
            writer.writerow(row)
    return len(unique)


def artifact_quality(
    positions: list[dict[str, Any]], *, now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect stored/exportable evidence, not infer current open vacancies."""
    from predoc_pipeline.boards.utils.geo import detect_location

    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    country_counts = {"explicit": 0, "derived_from_location": 0, "unknown": 0}
    availability = {"active": 0, "closed": 0, "unknown": 0}
    funding_unverified = 0
    older_than_week = 0
    unseen_time = 0
    urls: set[str] = set()
    for item in positions:
        country = str(item.get("country") or "").strip()
        if country and country != "Europe":
            country_counts["explicit"] += 1
        else:
            inferred, region = detect_location(str(item.get("location") or ""))
            if inferred and region == "Europe" and inferred != "Europe":
                country_counts["derived_from_location"] += 1
            else:
                country_counts["unknown"] += 1
        status = str(item.get("availability") or "unknown")
        if status not in availability:
            status = "unknown"
        availability[status] += 1
        if str(item.get("funding_status") or "unverified") != "verified":
            funding_unverified += 1
        last_seen = item.get("last_seen_at") or item.get("first_seen_at")
        try:
            observed = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("timestamp must be timezone-aware")
            if (timestamp - observed.astimezone(UTC)).days >= 7:
                older_than_week += 1
        except (TypeError, ValueError):
            unseen_time += 1
        link = str(item.get("url") or item.get("application_url") or "")
        if link:
            urls.add(link)
    return {
        "rows": len(positions), "unique_urls": len(urls),
        "duplicate_url_rows": len(positions) - len(urls),
        "country": country_counts,
        "availability": availability,
        "funding_unverified": funding_unverified,
        "last_seen_older_than_7d": older_than_week,
        "last_seen_missing_or_invalid": unseen_time,
        "verified_open_count": 0,
        "limits": {
            "no_current_application_verification": True,
            "current_availability_not_inferred": True,
            "funding_status_is_not_independently_verified": True,
            "seven_day_staleness_is_not_proof_of_closure": True,
        },
    }


async def collect(config_path: Path, rows: list[dict[str, Any]], output: Path,
                  report: dict[str, Any]) -> None:
    from predoc_pipeline.boards.config import HttpConfig
    from predoc_pipeline.ingest.life_sciences import (
        MAX_SOURCES,
        classify_post,
        discover,
        load_life_sources,
    )

    sources = [s.name for s in load_life_sources(config_path) if s.enabled]
    report['enabled_sources'] = len(sources)
    # Keep each discovery call within the same budget as scheduled collection.
    config = HttpConfig(timeout=15, max_retries=0, source_timeout=45)
    for offset in range(0, len(sources), MAX_SOURCES):
        selected = sources[offset:offset + MAX_SOURCES]
        posts, errors = await discover(config_path, config, selected_names=set(selected))
        accepted = 0
        for post in posts:
            row = classify_post(post)
            if row is None:
                continue
            # classify_post already derived and validated the European workplace.
            # Re-detecting from sparse index fields can erase that evidence.
            row.update({
                'research_fields': post.fields_of_research or '',
                'deadline': post.deadline.isoformat() if post.deadline else '',
                'deadline_note': post.deadline_text or '',
                'first_seen_at': report['collected_at'], 'last_seen_at': report['collected_at'],
                'availability': 'unknown',
            })
            rows.append(row)
            accepted += 1
        report['batches'].append({'sources': selected, 'candidates': len(posts),
                                  'accepted': accepted, 'errors': errors})
        report['exported_positions'] = write_csv(output, rows)
        report['artifact_quality'] = artifact_quality(rows)
        output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'sources_checked': min(offset + MAX_SOURCES, len(sources)),
                          'exported_positions': report['exported_positions'],
                          'source_issues': len(errors)}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, default=Path('data/career_jobs.ndjson'))
    parser.add_argument('--config', type=Path, default=Path('config/life_sciences.toml'))
    parser.add_argument('--output', type=Path, default=Path('exports/life_sciences_positions.csv'))
    parser.add_argument('--discover', action='store_true',
                        help='Also collect current public sources')
    args = parser.parse_args()
    rows = stored_positions(args.journal)
    report: dict[str, Any] = {'collected_at': datetime.now(UTC).isoformat(),
                              'stored_positions': len(rows), 'batches': []}
    if args.discover:
        asyncio.run(collect(args.config, rows, args.output, report))
    report['exported_positions'] = write_csv(args.output, rows)
    report['artifact_quality'] = artifact_quality(rows)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'csv': str(args.output), 'positions': report['exported_positions']}))


if __name__ == '__main__':
    main()
