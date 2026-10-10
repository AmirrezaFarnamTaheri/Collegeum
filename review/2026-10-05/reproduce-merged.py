"""Evidence for newly verified claims from the imported report; no live requests.

Assertions describe audited behavior. Files/databases are disposable; credentials
are placeholders. The browser and documentation checks are recorded separately.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import httpx

from predoc_pipeline.boards.collector import check_links
from predoc_pipeline.boards.config import HttpConfig, load_preferences
from predoc_pipeline.boards.heuristics import PI_RX
from predoc_pipeline.boards.utils.geo import detect_location
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.textproc import squish
from predoc_pipeline.core.urls import canonicalize_url, content_hash, url_hash
from predoc_pipeline.extract.gemini import (
    _AnthropicBackend,
    _OpenAICompatibleBackend,
    build_extractor,
)
from predoc_pipeline.extract.heuristic import disciplines_for
from predoc_pipeline.extract.prompt import SYSTEM_PROMPT, build_user_prompt
from predoc_pipeline.models import ExtractionResult, RawItem, parse_salary, sanitize_summary
from predoc_pipeline.pipeline import RunStats, _post_extract
from predoc_pipeline.publish.bot import _handle_tap
from predoc_pipeline.publish.feedback import FeedbackStore
from predoc_pipeline.routing import Channel, Router
from predoc_pipeline.settings import Settings


def main() -> None:
    evidence: dict[str, object] = {}
    prefs = load_preferences("config/preferences.toml")
    user = build_user_prompt(text="Paid economics research assistant. Apply now.",
                             source_url="https://example.org/job", title="Research Assistant")
    request = _OpenAICompatibleBackend().request("test", SYSTEM_PROMPT, user)
    assert request["response_format"] == {"type": "json_object"}
    assert not any("json" in message["content"].lower() for message in request["messages"])
    anthropic = _AnthropicBackend().request("test", SYSTEM_PROMPT, user)
    assert "tools" not in anthropic and "output_config" not in anthropic
    evidence["F52_output_contract_incomplete"] = {
        "json_mode": True, "json_instruction": False,
        "anthropic_keys": sorted(anthropic),
    }

    router = Router(prefs)
    institution = "University of Naples Federico II"
    sector = router.sector(institution)
    channel = router.channel(title="Predoctoral Research Assistant", institution=institution,
                             country="Italy")
    assert sector == "institutional" and channel is Channel.WEB
    evidence["F53_employer_substring_routing"] = {"institution": institution,
                                                "sector": sector, "channel": str(channel)}

    tags = disciplines_for(
        "Friendly work environment. Legal authorization. Microscopy and trade-offs."
    )
    assert "Law and Economics" in tags and "Environmental and Energy Economics" in tags
    evidence["F54_boilerplate_discipline_tags"] = tags
    match = PI_RX.search("working with Professor Amanda Gilmore Sponsoring Institution")
    assert match and match.group("name") == "Amanda Gilmore Sponsoring"
    evidence["F55_pi_field_boundary"] = match.group("name")

    geography = {text: detect_location(text) for text in (
        "Durham, NC", "York University", "Kent State University", "Hong Kong",
    )}
    assert geography["Durham, NC"][0] == "United Kingdom"
    assert geography["York University"][0] == "United Kingdom"
    assert geography["Hong Kong"][0] == "Other"
    evidence["F56_geography_homonyms"] = geography

    kind = router.position_kind(
        "Research Assistant",
        "The holder will enroll as a doctoral candidate and complete a PhD dissertation.",
    )
    assert kind == "predoc"
    evidence["F57_doctoral_role_defaults_to_predoc"] = kind

    salary = parse_salary("EUR 3.776,10 per month")
    canadian = parse_salary("CAD $60000 per year")
    assert salary[0] == 3.7761 and canadian[2] == "USD"
    evidence["F58_salary_locale_and_currency"] = {"european": salary, "canadian": canadian}
    title = "Research Assistant\u200b"
    assert squish(title) == title and content_hash(title) != content_hash(title[:-1])
    evidence["F59_zero_width_survives_normalization"] = {"hashes_differ": True}

    summary = sanitize_summary("Ihre Aufgaben: administrative Unterstützung.",
                               title="Research Assistant", institution="Example University")
    assert "academic coursework" in summary and "empirical research" in summary
    evidence["F63_generic_summary_invents_duties"] = summary

    records = [json.loads(line) for line in Path("data/listings.ndjson").read_text(
        encoding="utf-8"
    ).splitlines() if line.strip()]
    with TemporaryDirectory(prefix="collegeum-merge-") as directory:
        root = Path(directory)
        settings = Settings(_env_file=None, extraction_backend="heuristic")
        init(root / "audit.db")
        with Database(root / "audit.db") as db:
            title = "PhD Position in Economics"
            item = RawItem(source="audit", source_url="https://example.org/phd", title=title,
                           text="We are hiring for a paid doctoral position in economics.")
            result = ExtractionResult(is_vacancy=True, title=title,
                                      institution="Example University",
                                      application_url=item.source_url, confidence=0.99,
                                      summary="A paid doctoral position in economics.")
            stats = RunStats(run_id="merge-audit")
            out = _post_extract(item, gate_score=0.99, gate_lang="en",
            source_key=url_hash(item.source_url),
            digest=content_hash(item.text),
                                result=result, db=db, deduper=Deduplicator(), settings=settings,
                                stats=stats)
            assert out is None and stats.gated == 1
            evidence["F49_post_extraction_ignores_allowance"] = {
                "approved_extraction_discarded": True, "reasons": stats.gate_reasons,
            }

            record = dict(records[0], status="published", deadline=None, closed_at=None,
                          expired_at=None, last_checked_at="2020-01-01T00:00:00Z",
                          apply_url="https://example.org/jobs/one", source_url="https://example.org/jobs/one",
                          url_hash=url_hash("https://example.org/jobs/one"))
            db.import_rows([record])
            row = db.published_listings()[0]
            identifier = int(row["id"])
            requests: list[str] = []

            def respond(request: httpx.Request) -> httpx.Response:
                requests.append(str(request.url))
                return httpx.Response(404 if len(requests) == 1 else 200,
                                      text="Open economics research assistant position.")

            cfg = HttpConfig(default_min_interval=0, max_retries=0)
            transport = httpx.MockTransport(respond)
            found = check_links({identifier: (row["title"], row["apply_url"])}, cfg,
                                transport=transport)
            assert found[identifier] and "404" in found[identifier]
            db.mark_closed(identifier, found[identifier])
            retry = {int(r["id"]): (r["title"], r["apply_url"]) for r in db.due_for_recheck(0, 100)}
            assert not retry and check_links(retry, cfg, transport=transport) == {}
            assert len(requests) == 1
            evidence["F64_single_404_stops_future_verification"] = {
                "first_reason": found[identifier], "later_requests": 0,
            }

        store = FeedbackStore(root / "feedback.json")
        hash_value = "a" * 64
        row = {"url_hash": hash_value, "title": "Example role", "institution": "Example University",
               "apply_url": "https://example.org/job"}
        callback = {"id": "same-query", "from": {"id": 123}, "data": "fb|v|" + hash_value[:16]}
        bot = Mock()
        summary_counts = {"taps": 0, "ignored": 0}
        _handle_tap(bot, callback, {hash_value[:16]: row}, store, {123}, summary_counts)
        store.save()  # simulate saved marks followed by a crash before cursor persistence
        assert store.status(hash_value) == "valid"
        restored_store = FeedbackStore(root / "feedback.json")
        _handle_tap(bot, callback, {hash_value[:16]: row}, restored_store, {123}, summary_counts)
        assert restored_store.status(hash_value) is None
        evidence["F61_replayed_identical_callback_undoes_mark"] = {"after_replay": None}

    summary_text = "We collect data for research."
    full_text = "Predoctoral Research Assistant. " + summary_text
    original = Deduplicator()
    original.add(1, text=full_text, institution="Example University",
                 title="Predoctoral Research Assistant")
    restored = Deduplicator()
    restored.seed([{"id": 1, "summary": summary_text, "title": "Predoctoral Research Assistant",
                    "institution": "Example University", "principal_investigator": None,
                    "deadline": None}])
    before = original._lsh.signature(1)
    after = restored._lsh.signature(1)
    assert before and after and before.jaccard(after) < 1
    evidence["F65_restored_signature_differs"] = before.jaccard(after)

    memo_settings = Settings(_env_file=None, extraction_backend="memo",
                             memo_api_key="audit-placeholder", memo_base_url="",
                             custom_llm_base_url="http://localhost:8000/v1")
    extractor = build_extractor(memo_settings)
    try:
        assert extractor.base_url == "http://localhost:8000/v1"
        path = extractor._candidates[0].path("default")
        assert path == "/chat/completions"
        evidence["F66_memo_key_selects_local_chat_api"] = {
            "base_url": extractor.base_url, "path": path,
        }
    finally:
        extractor.close()

    # Extension to F22: identifier-like query keys are stripped globally.
    assert canonicalize_url("https://example.org/job?cid=1") == canonicalize_url(
        "https://example.org/job?cid=2"
    )
    evidence["F22_tracking_identifier_collision"] = True
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
