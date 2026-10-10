"""Memo must never borrow an unrelated endpoint or credential."""

import pytest

from predoc_pipeline.extract.gemini import ExtractionError, build_extractor
from predoc_pipeline.settings import Settings


@pytest.mark.parametrize('url,model', [('', ''), ('https://memo.example/v1', ''),
                                     ('', 'research-model'), ('  ', 'research-model')])
def test_memo_missing_explicit_configuration_fails_before_client_creation(monkeypatch, url, model):
    def unexpected(*args, **kwargs):
        pytest.fail('HTTP client must not be created for invalid memo configuration')

    monkeypatch.setattr('predoc_pipeline.extract.gemini.httpx.Client', unexpected)
    settings = Settings(_env_file=None, extraction_backend='memo',
                        memo_base_url=url, memo_model=model,
                        custom_llm_api_key='unrelated-key', custom_llm_model='unrelated-model')
    with pytest.raises(ExtractionError, match='MEMO_BASE_URL and MEMO_MODEL'):
        build_extractor(settings)


def test_memo_uses_only_explicit_memo_settings():
    settings = Settings(_env_file=None, extraction_backend='memo', memo_api_key='memo-key',
                        memo_base_url=' https://memo.example/v1 ', memo_model=' research-model ',
                        custom_llm_api_key='unrelated-key', custom_llm_model='unrelated-model')
    with build_extractor(settings) as extractor:
        assert extractor.base_url == 'https://memo.example/v1'
        assert extractor.model == 'research-model'
        assert extractor.api_key == 'memo-key'


def test_memo_missing_key_does_not_borrow_custom_credential():
    settings = Settings(_env_file=None, extraction_backend='memo', memo_api_key='',
                        memo_base_url='https://memo.example/v1', memo_model='research-model',
                        custom_llm_api_key='unrelated-key')
    with pytest.raises(ExtractionError, match='API key is required'):
        build_extractor(settings)
