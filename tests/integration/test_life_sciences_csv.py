"""CSV export preserves history, Unicode, unknown facts and safe spreadsheet cells."""
import csv
import json

from tools.export_life_sciences import stored_positions, write_csv


def test_export_includes_all_stored_life_positions_and_deduplicates_urls(tmp_path):
    life = {'category': 'life_sciences_phd', 'url': 'https://example.org/1',
            'title': 'PhD in زیست‌شناسی', 'employer': 'University', 'availability': 'closed'}
    path = tmp_path / 'journal.ndjson'
    path.write_text('\n'.join(json.dumps(row) for row in [life, life, {
        **life, 'category': 'data_analyst', 'url': 'https://example.org/2',
    }]), encoding='utf-8')
    output = tmp_path / 'positions.csv'
    assert write_csv(output, stored_positions(path)) == 1
    with output.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['title'] == life['title']
    assert rows[0]['availability'] == 'closed'
    assert rows[0]['funding_status'] == ''
    assert rows[0]['institution'] == 'University'


def test_export_escapes_formulas_and_keeps_valid_empty_csv(tmp_path):
    output = tmp_path / 'positions.csv'
    assert write_csv(output, [{'url': 'https://example.org/1', 'title': '=HYPERLINK(1)'}]) == 1
    with output.open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.DictReader(stream))['title'].startswith("'=")
    assert write_csv(output, []) == 0
    with output.open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []
