"""Missing advert facts must remain unknown in rendered dashboard outputs."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for rendered output checks')
def test_unknown_facts_and_deadline_analytics():
    page = Path('docs/index.html').read_text(encoding='utf-8')
    badge = 'function deadlineBadge' + page.split('function deadlineBadge', 1)[1].split(
        '// Dynamic Filter Chip Counts', 1)[0]
    analytics = 'function renderAnalytics' + page.split('function renderAnalytics', 1)[1].split(
        '// Modal Dossier', 1)[0]
    modal = page.split('// Modal Dossier', 1)[1]
    dossier = 'const place' + modal.split('const place', 1)[1].split(
        "$('#modal-grid').innerHTML", 1)[0]
    script = """
const assert = require('node:assert/strict');
const nodes = new Map();
const $ = id => {if(!nodes.has(id))nodes.set(id,{innerHTML:''});return nodes.get(id);};
const esc = value => String(value);
const formatDate = value => value;
const formatDegree = value => value;
const resetAll = () => {};
const listings = [
 {deadline:null,days_left:null,visa:'unstated'},
 {deadline:'2026-11-31',days_left:null,visa:'explicit'},
 {deadline:null,days_left:null,deadline_note:'Rolling review',visa:'inferred'},
 {deadline:'2026-10-04',days_left:-1,visa:'not_offered'},
 {deadline:'2026-10-06',days_left:1},
];
""" + badge + analytics + r"""
renderAnalytics(listings);
const html = $('#analytics-wrap').innerHTML;
assert.match(html,/20%[\s\S]*Rolling Review/);
assert.match(html,/2 unstated or unverified; 1 past deadline/);
assert.match(html,/1 stated, 1 inferred; 2 unknown/);
assert.match(html,/title="Unstated or unverified: 2"/);
assert.match(html,/title="Past deadline: 1"/);
assert.doesNotMatch(html,/Visa Friendly/);
assert.match(html,/0 distinct reported institution names/);
assert.doesNotMatch(html,/75 institutions/);
renderAnalytics(listings.map((row,index) => ({...row,
 institution:['Example University','example university',
              ' Unknown institution ','','Unstated'][index]})));
assert.match($('#analytics-wrap').innerHTML,/1 distinct reported institution names/);
renderAnalytics(listings.map((row,index) => ({...row,
 institution:['__proto__','constructor','toString','__proto__','constructor'][index],
 country:['__proto__','constructor','toString','__proto__','constructor'][index]})));
const reservedNamesHtml = $('#analytics-wrap').innerHTML;
assert.doesNotMatch(reservedNamesHtml,/NaN|\[object Object\]|function Object/);
assert.match(reservedNamesHtml,/__proto__/);
assert.match(reservedNamesHtml,/constructor/);
assert.match(reservedNamesHtml,/toString/);
assert.equal((reservedNamesHtml.match(/>2 <span/g)||[]).length,2);
assert.equal((reservedNamesHtml.match(/>2 roles/g)||[]).length,2);
renderAnalytics([]);
assert.match($('#analytics-wrap').innerHTML,/No data available/);
const item = {}, b = deadlineBadge(item), sal = '', sectorLabel = 'Unstated';
""" + dossier + """
const values = Object.fromEntries(gridData);
for(const field of ['Duration','Compensation','Start Date / Term','Disciplines','Deadline']) {
 assert.equal(values[field],'Unstated',field);
}
"""
    result = subprocess.run([shutil.which('node')], input=script,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
