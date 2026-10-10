"""Configured research categories survive extraction and route correctly."""

import json
from unittest.mock import Mock

import httpx
import pytest

from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.extract.gemini import (
    ExtractionError,
    Extractor,
    _AnthropicBackend,
    _OpenAICompatibleBackend,
)
from predoc_pipeline.extract.heuristic import HeuristicExtractor
from predoc_pipeline.extract.prompt import SYSTEM_PROMPT, build_user_prompt
from predoc_pipeline.models import EXTRACTION_JSON_SCHEMA, ExtractionResult, RawItem
from predoc_pipeline.pipeline import RunStats, _process
from predoc_pipeline.policy import Policy
from predoc_pipeline.routing import Channel, Router
from predoc_pipeline.settings import Settings


@pytest.mark.parametrize(
    "title,country,allow_phd,accepted",
    [
        ("PhD Position in Economics", "United Kingdom", True, True),
        ("PhD Position in Economics", "United Kingdom", False, False),
        ("Postdoctoral Fellow in Economics", "United Kingdom", False, True),
        ("Predoctoral Fellow in Economics", "United States", False, True),
        ("Professor in Economics", "United Kingdom", True, False),
    ],
)
def test_research_scope_through_processing(tmp_path, title, country, allow_phd, accepted):
    prefs = load_preferences("config/preferences.toml")
    prefs.filters.exclude_phd_positions = not allow_phd
    policy = Policy(prefs, trust_model_fields=True)
    item = RawItem(
        source="test",
        source_url="https://example.org/opening",
        title=title,
        text=f"We are hiring a paid {title} at University of Oxford in {country}. "
        "Research in applied microeconomics and causal inference using Stata.",
        hints={"board": "test"},
    )
    extractor = Mock()
    extractor.extract.return_value = ExtractionResult(
        is_vacancy=True,
        title=title,
        institution="University of Oxford",
        country=country,
        application_url=item.source_url,
        summary="Paid research in applied microeconomics and causal inference.",
        disciplines=["Applied Microeconomics"],
        confidence=0.99,
    )
    path = tmp_path / "scope.db"
    init(path)
    with Database(path) as db:
        listing = _process(
            item,
            db=db,
            extractor=extractor,
            deduper=Deduplicator(),
            settings=Settings(_env_file=None, confidence_threshold=0.5),
            stats=RunStats(),
            policy=policy,
        )
        assert (listing is not None) is accepted
        if accepted:
            assert Router(prefs).channel_for(listing) == Channel.WEB
            assert db.counts()["listings"] == 1
        else:
            assert db.counts()["listings"] == 0


@pytest.mark.parametrize("backend", [_OpenAICompatibleBackend(), _AnthropicBackend()])
def test_non_gemini_requests_include_complete_json_contract(backend):
    user = build_user_prompt(text="An open research role.", source_url="https://example.org")
    request = backend.request("test-model", SYSTEM_PROMPT, user)
    system = request.get("system") or request["messages"][0]["content"]
    assert "JSON" in system
    schema = json.loads(system.split("OUTPUT JSON SCHEMA:\n", 1)[1])
    assert schema == EXTRACTION_JSON_SCHEMA
    assert "POSTDOCTORAL" in system and "United States" in system


@pytest.mark.parametrize("allow_phd", [True, False])
def test_heuristic_doctoral_extraction_respects_category_policy(allow_phd):
    prefs = load_preferences("config/preferences.toml")
    prefs.filters.exclude_phd_positions = not allow_phd
    result = HeuristicExtractor(prefs).extract(
        title="PhD Researcher in Economics at University of Oxford",
        text="We are hiring a PhD researcher for economics research. Apply now.",
        source_url="https://example.org/job",
    )
    assert result.is_vacancy is allow_phd


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>gateway error</html>"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"is_vacancy": True, "confidence": 0.99}
        )}}]}),
    ],
)
@pytest.mark.parametrize("with_fallback", [True, False])
def test_malformed_success_uses_fallback_or_extraction_error(response, with_fallback):
    fallback = Mock()
    fallback.extract.return_value = ExtractionResult(is_vacancy=False, confidence=0.5)
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        extractor = Extractor(
            api_key="placeholder",
            model="test",
            base_url="https://example.org/v1",
            backend="openai",
            limiter=Mock(),
            client=client,
            fallback_extractor=fallback if with_fallback else None,
        )
        if with_fallback:
            result = extractor.extract(text="An economics research role.",
                                       source_url="https://example.org/job")
            assert result.is_heuristic_fallback
            fallback.extract.assert_called_once()
        else:
            with pytest.raises(ExtractionError):
                extractor.extract(text="An economics research role.",
                                  source_url="https://example.org/job")
