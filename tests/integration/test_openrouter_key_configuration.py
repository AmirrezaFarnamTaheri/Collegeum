"""OpenRouter key configuration must reach extraction without inventing keys."""

import pytest
from pydantic import ValidationError

from predoc_pipeline.extract.gemini import Extractor, build_extractor
from predoc_pipeline.extract.heuristic import HeuristicExtractor
from predoc_pipeline.settings import Settings

_NO_KEYS = {
    name: "" for name in (
        "gemini_api_key", "groq_api_key", "nvidia_api_key", "openai_api_key",
        "anthropic_api_key", "openrouter_api_key", "openrouter_api_keys",
        "mistral_api_key", "memo_api_key", "custom_llm_api_key",
    )
}


def _settings(**overrides):
    return Settings(_env_file=None, **{**_NO_KEYS, "extraction_backend": "auto", **overrides})


@pytest.mark.parametrize("keys", [
    "first,second", "first; second", "first\nsecond", '["first", "second"]',
    ["first", "second"], ("first", "second"),
])
def test_plural_keys_select_openrouter_for_automatic_extraction(keys):
    settings = _settings(openrouter_api_keys=keys)
    with build_extractor(settings) as extractor:
        assert isinstance(extractor, Extractor)
        assert extractor.api_key == "first"
        assert extractor.base_url == settings.openrouter_base_url
        assert extractor.rotator.get_key() == "first"
        assert extractor.rotator.get_key() == "second"


def test_single_key_setting_still_accepts_multiple_keys():
    with build_extractor(_settings(openrouter_api_key="first, second; third")) as extractor:
        assert extractor.rotator.get_key() == "first"
        assert extractor.rotator.get_key() == "second"
        assert extractor.rotator.get_key() == "third"


def test_combined_key_settings_preserve_order_and_deduplicate():
    settings = _settings(
        openrouter_api_keys=["first", "second", "first"],
        openrouter_api_key="second, third",
    )
    assert settings.get_openrouter_keys() == ["first", "second", "third"]
    with build_extractor(settings) as extractor:
        assert [extractor.rotator.get_key() for _ in range(4)] == [
            "first", "second", "third", "first",
        ]


def test_plural_keys_preserve_existing_provider_precedence():
    settings = _settings(groq_api_key="groq-key", openrouter_api_keys=["openrouter-key"])
    with build_extractor(settings) as extractor:
        assert extractor.api_key == "groq-key"
        assert extractor.base_url == settings.groq_base_url


@pytest.mark.parametrize("keys", ["", " , ;\n", "[]", ["", " "]])
def test_empty_plural_keys_keep_the_heuristic_fallback(keys):
    with build_extractor(_settings(openrouter_api_keys=keys)) as extractor:
        assert isinstance(extractor, HeuristicExtractor)


@pytest.mark.parametrize("keys", ['["first", "second"', "[first, second]", '["first",]'])
def test_malformed_json_key_arrays_are_configuration_errors(monkeypatch, keys):
    monkeypatch.setenv("OPENROUTER_API_KEYS", keys)
    with pytest.raises(ValidationError, match="valid JSON array"):
        Settings(_env_file=None)


@pytest.mark.parametrize("keys", [
    '["first", null]', '["first", 42]', '["first", true]',
    '["first", {"key": "second"}]', '["first", ["second"]]',
    ["first", None], ["first", 42], ["first", True], ("first", {}),
])
def test_key_array_members_must_be_strings(keys):
    with pytest.raises(ValidationError, match="contain only strings"):
        _settings(openrouter_api_keys=keys)
