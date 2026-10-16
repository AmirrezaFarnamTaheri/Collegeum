"""Preview and selectively correct historical non-predoc posts in-place.

Default: READ-ONLY. No Telegram requests, deletion, new posts, or journal edits.
Use --apply only after reviewing the original vacancies and confirming the
exact journal SHA and intended channel. Telegram editMessageText is attempted
only for unique bot-publication receipts; shared digest IDs require a separate
human-authored correction that preserves all the digest's legitimate listings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_JOURNAL = Path("data/listings.ndjson")
_KINDS = {
    "phd": "Doctoral-student opportunity",
    "postdoc": "Postdoctoral opportunity",
    "research": "PhD-qualified research position",
}


@dataclass(frozen=True, slots=True)
class Correction:
    listing_id: int
    telegram_message_id: int
    kind: str
    title: str
    institution: str
    apply_url: str
    min_degree: str
    shared_receipt: bool


def plan_records(rows: list[dict[str, Any]]) -> list[Correction]:
    """Inspect only published receipts and use the same role classifier as delivery."""
    from predoc_pipeline.routing import Router

    identifiers: set[int] = set()
    receipts: Counter[int] = Counter()
    for row in rows:
        identifier = row.get("id")
        if type(identifier) is not int or identifier <= 0 or identifier in identifiers:
            raise ValueError("journal contains invalid or repeated listing IDs")
        identifiers.add(identifier)
        message_id = row.get("telegram_message_id")
        if type(message_id) is int and message_id > 0:
            receipts[message_id] += 1

    candidates: list[Correction] = []
    for row in rows:
        message_id = row.get("telegram_message_id")
        if (row.get("status") != "published" or type(message_id) is not int
                or message_id <= 0):
            continue
        kind = Router.kind_for_row(row)
        if kind == "predoc":
            continue
        candidates.append(Correction(
            listing_id=row["id"], telegram_message_id=message_id, kind=kind,
            title=str(row.get("title") or ""), institution=str(row.get("institution") or ""),
            apply_url=str(row.get("apply_url") or ""),
            min_degree=str(row.get("min_degree") or ""),
            shared_receipt=receipts[message_id] != 1,
        ))
    return sorted(candidates, key=lambda item: item.listing_id)


def plan_file(path: Path) -> tuple[str, list[Correction]]:
    """Return exact-byte journal digest and nonpredoc receipts without mutation."""
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.decode("utf-8").split("\n"), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"journal line {index} must be a JSON object")
        rows.append(row)
    return hashlib.sha256(raw).hexdigest(), plan_records(rows)


def _public_apply_url(url: str) -> bool:
    """Never link users back to a placeholder, credential URL, or private host."""
    from predoc_pipeline.core.network_safety import UnsafeDestination, validate_public_url
    from predoc_pipeline.core.output_quality import application_url_issue

    if not url or len(url) > 1024 or application_url_issue(url):
        return False
    try:
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None:
            return False
        validate_public_url(url, resolve_dns=False)
    except (UnsafeDestination, ValueError):
        return False
    return True


def correction_html(item: Correction) -> str:
    """Replacement for one already-sent bot message, never a new notification."""
    kind = _KINDS.get(item.kind, "Non-predoctoral position")
    title = escape(item.title[:180])
    institution = escape(item.institution[:140])
    lines = [
        "⚠️ <b>Correction: not a predoc opening</b>",
        "This vacancy was previously shared in the predoc channel by mistake.",
        "",
        f"<b>{title}</b>",
        f"🏛 {institution}",
        f"Role: {escape(kind)}.",
        "Please check the original advert for qualifications and deadlines.",
    ]
    if item.min_degree.strip().lower().replace(".", "") in {"phd", "doctoral", "doctorate"}:
        lines.insert(-1, "Minimum qualification recorded: PhD.")
    if _public_apply_url(item.apply_url):
        lines.append(f'<a href="{escape(item.apply_url, quote=True)}">Original advert</a>')
    return "\n".join(lines)


def apply_corrections(
    plan: list[Correction], *, reviewed_ids: set[int], journal_sha256: str,
    confirm_sha256: str, channel: str, confirm_channel: str, client: Any,
) -> dict[str, Any]:
    """Require exact human selection and preflight ALL edits before any network I/O."""
    if not reviewed_ids:
        raise ValueError("explicit review of listing IDs is required")
    if len(journal_sha256) != 64 or confirm_sha256 != journal_sha256:
        raise ValueError("journal digest confirmation mismatch")
    if not channel or channel != confirm_channel:
        raise ValueError("Telegram channel confirmation mismatch")
    by_id = {item.listing_id: item for item in plan}
    if len(by_id) != len(plan) or reviewed_ids - by_id.keys():
        raise ValueError("reviewed IDs include an unknown candidate")
    selected = [by_id[key] for key in sorted(reviewed_ids)]
    if any(item.shared_receipt for item in selected):
        raise ValueError("shared Telegram digest receipt cannot be edited as one job")
    if len({item.telegram_message_id for item in selected}) != len(selected):
        raise ValueError("two reviewed listings share a Telegram message")
    if client is None:
        raise ValueError("a configured Telegram client is required")

    report: dict[str, Any] = {"edited_listing_ids": [], "failed": []}
    for item in selected:
        payload = {
            "chat_id": channel, "message_id": item.telegram_message_id,
            "text": correction_html(item), "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": []},
        }
        try:
            client.call("editMessageText", payload)
        except Exception as exc:
            # Do not expose bot tokens, request URLs or subscriber data in logs.
            report["failed"].append({
                "listing_id": item.listing_id, "error_type": type(exc).__name__,
            })
        else:
            report["edited_listing_ids"].append(item.listing_id)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewed-ids", default="", help="Comma-separated journal listing IDs")
    parser.add_argument("--confirm-sha256", default="")
    parser.add_argument("--channel", default=os.environ.get("TELEGRAM_PUBLIC_CHANNEL_ID", ""))
    parser.add_argument("--confirm-channel", default="")
    args = parser.parse_args()
    digest, plan = plan_file(args.journal)
    result: dict[str, Any] = {
        "journal_sha256": digest, "candidate_count": len(plan),
        "candidates": [asdict(item) for item in plan],
        "dry_run": not args.apply,
    }
    if args.apply:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            parser.error("TELEGRAM_BOT_TOKEN is required for reviewed corrections")
        try:
            reviewed = {
                int(value) for value in args.reviewed_ids.split(",") if value.strip()
            }
        except ValueError:
            parser.error("--reviewed-ids must contain only integer listing IDs")
        # Reject all invalid approvals before creating any network client.
        apply_corrections(
            plan, reviewed_ids=reviewed, journal_sha256=digest,
            confirm_sha256=args.confirm_sha256, channel=args.channel,
            confirm_channel=args.confirm_channel, client=_ValidationOnly(),
        )
        # The journal must remain the same even if a pipeline ran during review.
        if hashlib.sha256(args.journal.read_bytes()).hexdigest() != digest:
            parser.error("journal changed during approval; repeat the preview")
        from predoc_pipeline.publish.telegram import TelegramClient

        with TelegramClient(bot_token=token) as client:
            result["corrections"] = apply_corrections(
                plan, reviewed_ids=reviewed, journal_sha256=digest,
                confirm_sha256=args.confirm_sha256, channel=args.channel,
                confirm_channel=args.confirm_channel, client=client,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


class _ValidationOnly:
    """Records no side effects; used only to validate an operator's CLI selection."""

    def call(self, method: str, payload: dict[str, Any]) -> None:
        # No real Telegram request. The preflight call is permitted only to
        # validate selections before touching credentials.
        return None


if __name__ == "__main__":
    main()
