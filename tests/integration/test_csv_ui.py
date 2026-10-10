"""Execute the actual dashboard selection and CSV functions, then parse exports."""

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def run_page_functions(script):
    page = Path("docs/index.html").read_text(encoding="utf-8")
    selection = "function activeListingFilters" + page.split(
        "function activeListingFilters", 1
    )[1].split("// Board Filter & Render Engine", 1)[0]
    serialization = "function csvCell" + page.split("function csvCell", 1)[1].split(
        "$('#export-csv-btn').onclick", 1
    )[0]
    result = subprocess.run(
        [shutil.which("node"), "-e", selection + serialization + script],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for dashboard checks")
def test_board_and_export_share_categories_filters_and_sorting():
    result = run_page_functions("""
const assert = require('node:assert/strict');
const rows = [
 {id:1,title:'Zebra',institution:'Beta',kind:'predoc',country:'United States',
  sector:'academic',days_left:3,visa:'explicit',disciplines:['micro'],
  principal_investigator:'Alice',first_seen_at:'2026-01-01'},
 {id:2,title:'Alpha',institution:'Alpha',kind:'phd',country:'Canada',
  sector:'academic',days_left:null,visa:'unknown',disciplines:['macro'],
  first_seen_at:'2026-03-01'},
 {id:3,title:'Beta',institution:'Gamma',kind:'postdoc',country:'United States',
  sector:'institutional',days_left:7,visa:'explicit',disciplines:['micro'],
  first_seen_at:'2026-02-01'},
 {id:4,title:'Delta',kind:'predoc',country:'France',days_left:-1}
];
const base = {category:'all',sort:'d'};
const cases = [
 [{category:'us'},[1]], [{category:'postdoc-phd'},[3,2]],
 [{category:'institutional'},[3]], [{category:'closing-soon'},[1,3]],
 [{disc:'macro'},[2]], [{kindSel:'postdoc'},[3]], [{sector:'academic'},[1,2]],
 [{country:'France'},[4]], [{visa:'explicit'},[1,3]], [{q:'alice'},[1]],
 [{category:'us',disc:'micro',visa:'explicit',q:'beta'},[1]],
 [{category:'us',kindSel:'phd'},[]],
 [{sort:'t'},[2,3,4,1]], [{sort:'i'},[4,2,1,3]],
 [{sort:'newest'},[2,3,1,4]], [{},[4,1,3,2]]
];
for (const [overrides, expected] of cases) {
 assert.deepEqual(selectListingRows(rows,{...base,...overrides}).map(r=>r.id), expected);
}
assert.deepEqual(rows.map(r=>r.id),[1,2,3,4]);
console.log(JSON.stringify({passed:cases.length}));
""")
    assert result["passed"] == 16
    page = Path("docs/index.html").read_text(encoding="utf-8")
    draw = page.split("function draw()", 1)[1].split("// Render Ledger Rows", 1)[0]
    export = page.split("$('#export-csv-btn').onclick", 1)[1].split(
        "// Load Listings Data", 1
    )[0]
    shared = "selectListingRows(listings, activeListingFilters())"
    assert shared in draw and shared in export
    assert "new Blob(['\\uFEFF', csv]" in export


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for dashboard checks")
@pytest.mark.parametrize("value", [
    '=HYPERLINK("https://example.org","open")', '+1+1', '-1+1', '@SUM(1)',
    '\t=1+1', '\r=1+1', '\n=1+1', '  =1+1', '\ufeff=1+1', '＝1+1',
    'Oxford, "Economics"\n😀漢字', "O'Brien", 'https://example.org/?a=1&b=2',
])
def test_every_csv_column_quotes_and_neutralizes_formula_text(value):
    fields = [
        'id', 'title', 'institution', 'principal_investigator', 'country', 'city',
        'kind', 'sector', 'deadline', 'visa', 'salary_raw', 'min_degree', 'start_term',
        'apply_url',
    ]
    record = dict.fromkeys(fields, value)
    record.update(tools_required=[value], tools_preferred=[value])
    result = run_page_functions(
        "function formatSalary() {return '';}\n"
        f"console.log(JSON.stringify(serializeListingsCsv([{json.dumps(record)}])));"
    )
    parsed = list(csv.reader(io.StringIO(result, newline="")))
    assert len(parsed) == 2
    assert len(parsed[0]) == len(parsed[1]) == 16
    dangerous = value not in [
        'Oxford, "Economics"\n😀漢字', "O'Brien", 'https://example.org/?a=1&b=2',
    ]
    expected = "[text] " + value if dangerous else value
    assert parsed[1] == [expected] * 16


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for dashboard checks")
def test_empty_csv_and_zero_id_preserve_shape():
    result = run_page_functions("""
function formatSalary() {return '';}
console.log(JSON.stringify([serializeListingsCsv([]),serializeListingsCsv([{id:0}])]));
""")
    assert len(list(csv.reader(io.StringIO(result[0])))) == 1
    parsed = list(csv.reader(io.StringIO(result[1])))
    assert parsed[1] == ['0'] + [''] * 15
