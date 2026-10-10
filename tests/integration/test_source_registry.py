"""Shared registry validation and both loader consumers."""

import pytest

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.registry import read_registry
from predoc_pipeline.ingest.sources import load_sources


@pytest.mark.parametrize('second_kind', ['board', 'feed', 'portal'])
def test_duplicate_ids_fail_across_collectors(tmp_path, second_kind):
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="same"\ntype="predoc_org"\n'
                    f'[[{second_kind}]]\nname="same"\nenabled=false\n'
                    'url="https://example.org/jobs"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate source name: same'):
        read_registry(file)


@pytest.mark.parametrize('name', ['""', '"  "', '" padded "', '123'])
def test_invalid_identity_is_not_silently_skipped(tmp_path, name):
    file = tmp_path / 'sources.toml'
    file.write_text(f'[[feed]]\nname={name}\nurl="https://example.org/feed"\n')
    with pytest.raises(ValueError, match='trimmed name'):
        read_registry(file)


def test_string_disabled_does_not_enable_a_source(tmp_path):
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="test"\ntype="predoc_org"\nenabled="false"\n')
    with pytest.raises(ValueError, match='enabled must be a boolean'):
        read_registry(file)


def test_current_registry_has_one_dedicated_predoc_adapter():
    boards = load_board_sources('config/sources.toml')
    assert [source.type for source in boards if source.name == 'predoc_org'] == ['predoc_org']


@pytest.mark.parametrize('field,error', [
    ('', 'url must'),
    ('url=""', 'url must'),
    ('url=123', 'url must'),
    ('url="/relative"', 'url must'),
    ('url="https://"', 'url must'),
    ('url="file:///tmp/jobs"', 'url must'),
    ('url="https://example.org:bad/jobs"', 'url must'),
    ('url=" https://example.org/jobs"', 'url must'),
    ('url="https://example.org/jobs"\nverified="false"', 'verified must'),
    ('url="https://example.org/jobs"\nfollow_links="false"', 'follow_links must'),
    ('url="https://example.org/jobs"\nmax_items=-1', 'max_items must'),
    ('url="https://example.org/jobs"\nmax_items=0', 'max_items must'),
    ('url="https://example.org/jobs"\nmax_items=true', 'max_items must'),
    ('url="https://example.org/jobs"\nmax_items=1.5', 'max_items must'),
    ('url="https://example.org/jobs"\ntags="economics"', 'tags must'),
    ('url="https://example.org/jobs"\ntags=[123]', 'tags must'),
])
def test_invalid_fields_are_never_silently_dropped(tmp_path, field, error):
    file = tmp_path / 'sources.toml'
    file.write_text(f'[[feed]]\nname="test"\n{field}\n', encoding='utf-8')
    with pytest.raises(ValueError, match=error):
        read_registry(file)


@pytest.mark.parametrize('loader', [load_sources, load_board_sources])
@pytest.mark.parametrize('kind', ['feed', 'portal'])
def test_both_loaders_validate_other_collector_entries(tmp_path, loader, kind):
    file = tmp_path / 'sources.toml'
    file.write_text(f'[[{kind}]]\nname="test"\nurl="/relative"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='url must'):
        loader(file)


def test_valid_fields_preserve_values(tmp_path):
    file = tmp_path / 'sources.toml'
    file.write_text('[[portal]]\nname="test"\nurl="https://example.org:443/jobs?a=1"\n'
                    'max_items=1\nverified=false\nfollow_links=true\ntags=["economics"]\n')
    source = load_sources(file)[0]
    assert source.max_items == 1
    assert source.follow_links is True
    assert source.verified is False
    assert source.tags == ['economics']


@pytest.mark.parametrize('other_kind', ['board', 'feed', 'portal'])
def test_resolved_identity_collision_fails(tmp_path, monkeypatch, other_kind):
    monkeypatch.setenv('COLLEGEUM_TEST_SOURCE_ID', 'existing')
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="${COLLEGEUM_TEST_SOURCE_ID}"\ntype="predoc_org"\n'
                    f'[[{other_kind}]]\nname="existing"\nurl="https://example.org"\n')
    with pytest.raises(ValueError, match='duplicate source name: existing'):
        read_registry(file)


@pytest.mark.parametrize('value', [None, '', ' padded '])
def test_unusable_resolved_name_fails(tmp_path, monkeypatch, value):
    monkeypatch.delenv('COLLEGEUM_TEST_SOURCE_ID', raising=False)
    if value is not None:
        monkeypatch.setenv('COLLEGEUM_TEST_SOURCE_ID', value)
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="${COLLEGEUM_TEST_SOURCE_ID}"\ntype="predoc_org"\n')
    with pytest.raises(ValueError, match='trimmed resolved name'):
        read_registry(file)


def test_names_resolve_consistently_across_loaders(tmp_path, monkeypatch):
    monkeypatch.delenv('COLLEGEUM_TEST_SOURCE_ID', raising=False)
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="${COLLEGEUM_TEST_SOURCE_ID:-board_default}"\n'
                    'type="predoc_org"\n[[feed]]\nname="${COLLEGEUM_TEST_SOURCE_ID:-feed_default}"\n'
                    'url="https://example.org/feed"\n')
    assert load_board_sources(file)[0].name == 'board_default'
    assert load_sources(file)[0].name == 'feed_default'


def test_environment_values_are_not_interpolated_twice(tmp_path, monkeypatch):
    monkeypatch.setenv('COLLEGEUM_TEST_SOURCE_ID', '${COLLEGEUM_TEST_SECOND_ID}')
    monkeypatch.setenv('COLLEGEUM_TEST_SECOND_ID', 'existing')
    file = tmp_path / 'sources.toml'
    file.write_text('[[board]]\nname="${COLLEGEUM_TEST_SOURCE_ID}"\ntype="predoc_org"\n'
                    '[[feed]]\nname="existing"\nurl="https://example.org/feed"\n')
    assert load_board_sources(file)[0].name == '${COLLEGEUM_TEST_SECOND_ID}'
    assert load_sources(file)[0].name == 'existing'
