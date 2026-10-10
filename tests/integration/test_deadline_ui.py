"""Run actual dashboard date, draw and refresh functions with a controlled clock."""

import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from predoc_pipeline import state


def run_dates(script, *, lifecycle=False):
    page = Path('docs/index.html').read_text(encoding='utf-8')
    pieces = [
        'function deadlineDays' + page.split('function deadlineDays', 1)[1].split(
            'function enrichItem', 1)[0],
        'function formatDate' + page.split('function formatDate', 1)[1].split(
            'function formatSalary', 1)[0],
        'function deadlineBadge' + page.split('function deadlineBadge', 1)[1].split(
            '// Populate dropdowns', 1)[0],
        'function activeListingFilters' + page.split('function activeListingFilters', 1)[1].split(
            '// Render Ledger Rows', 1)[0],
        'function healthPresentation' + page.split('function healthPresentation', 1)[1].split(
            '// Health Telemetry', 1)[0],
    ]
    setup = """
const assert = require('node:assert/strict');
let clock = Date.parse('2026-10-05T23:59:59Z');
Date.now = () => clock;
let listings = [], currentKind = 'closing-soon', viewMode = 'ledger';
let listingsGeneratedAt = '2026-10-04T06:00:00Z', currentModalListing = null;
let deadlineRenderDay = null;
let pipelineHealth = {status:'ok',generated_at:'2026-10-05T23:00:00Z'};
const nodes = new Map();
const $ = id => {
 if (!nodes.has(id)) nodes.set(id, {value: id === '#filter-sort' ? 'd' : '',
   textContent:'',style:{},classList:{toggle(){}},innerHTML:''});
 return nodes.get(id);
};
let rendered = [];
function renderLedger(rows) {rendered = rows.map(r=>r.id);}
function renderGrid() {}
function renderAnalytics() {}
function esc(text) {return String(text);}
const timers = [], cleared = [], intervals = [], handlers = {};
function setTimeout(fn, delay) {timers.push({fn,delay}); return timers.length;}
function clearTimeout(id) {cleared.push(id);}
function setInterval(fn,delay) {intervals.push({fn,delay});}
const document = {hidden:false, addEventListener(name,fn) {handlers[name]=fn;}};
const window = {addEventListener(name,fn) {handlers[name]=fn;}};
"""
    if lifecycle:
        pieces.append('function deadlineRefreshDelay' + page.split(
            'function deadlineRefreshDelay', 1)[1].split('function healthPresentation', 1)[0])
    result = subprocess.run(
        [shutil.which('node'), '-e', setup + '\n'.join(pieces) + script],
        capture_output=True, check=True, text=True, encoding='utf-8',
        env={**os.environ, 'TZ': 'America/Los_Angeles'},
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for dashboard verification')
def test_calendar_deadlines_are_current_and_timezone_independent():
    result = run_dates("""
const cases = [
 ['2026-10-06', '2026-10-05T23:59:59Z', 1],
 ['2026-10-05T00:00:00Z', '2026-10-05T23:59:59Z', 0],
 ['2026-10-05', '2026-10-06T00:00:00Z', -1],
 ['2026-10-06T00:00:00+05:30', '2026-10-05T12:00:00Z', 0],
 ['2026-10-05T23:30:00-04:00', '2026-10-05T12:00:00Z', 1],
 ['2024-02-29', '2024-02-28T23:59:59Z', 1],
 ['2027-01-01', '2026-12-31T23:59:59Z', 1],
 ['2026-03-09', '2026-03-08T12:00:00Z', 1],
 ['2026-11-02', '2026-11-01T12:00:00Z', 1],
 ['0001-01-02', '0001-01-01T12:00:00Z', 1],
 ['2026-02-30', '2026-10-05T12:00:00Z', null],
 ['2026-13-01', '2026-10-05T12:00:00Z', null],
 ['2026-10-06T00:00:00', '2026-10-05T12:00:00Z', null],
 ['2026-10-06TgarbageZ', '2026-10-05T12:00:00Z', null],
 [null, '2026-10-05T12:00:00Z', null],
 ['bad', '2026-10-05T12:00:00Z', null]
];
for (const [deadline, now, expected] of cases) {
 assert.equal(deadlineDays({deadline,days_left:999},Date.parse(now)), expected);
}
assert.equal(deadlineDays({deadline:'2026-10-06'},NaN),null);
assert.equal(deadlineDays({deadline:'2026-10-06'},1e300),null);
assert.equal(formatDate('2026-10-06'),'6 Oct 2026');
assert.equal(snapshotLabel('2026-10-04T12:00:00Z',Date.parse('2026-10-05T12:00:00Z')),
 'Listings snapshot: 1d old');
assert.equal(snapshotLabel('bad'),'Snapshot age unavailable');
assert.equal(snapshotLabel('2027-01-01'),'Snapshot age unavailable');
assert.equal(deadlineBadge({deadline:'bad',days_left:null}).label,'Check deadline');
assert.equal(deadlineBadge({deadline:null,days_left:null}).label,'Unstated');
assert.equal(deadlineBadge({deadline:null,deadline_note:'Rolling review',days_left:null}).label,
 'Rolling');
console.log(JSON.stringify({passed:cases.length}));
""")
    assert result['passed'] == 16


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for dashboard verification')
def test_midnight_and_foreground_refresh_update_draw_chips_and_open_modal():
    result = run_dates("""
handlers.focus();
assert.equal(deadlineRenderDay,null);
assert.deepEqual(rendered,[]);
listings = [
 {id:1,title:'Tomorrow',deadline:'2026-10-06',days_left:999},
 {id:2,title:'Next week',deadline:'2026-10-13',days_left:999},
 {id:3,title:'Yesterday',deadline:'2026-10-04',days_left:999},
 {id:4,title:'Unknown',deadline:null,days_left:0}
];
draw();
assert.deepEqual(rendered,[1]);
assert.equal($('#count-soon').textContent,1);
assert.equal(deadlineBadge(listings[0]).label,'1d left');
assert.equal(deadlineBadge(listings[2]).label,'Closed');
currentModalListing = listings[0];
assert.equal(timers[0].delay,1000);
clock = Date.parse('2026-10-06T00:00:00Z');
timers[0].fn();
assert.deepEqual(rendered,[1,2]);
assert.equal($('#count-soon').textContent,2);
assert.equal($('#modal-deadline-status').textContent,'Today');
assert.equal($('#modal-deadline-value').textContent,'Today (6 Oct 2026)');
assert.ok($('#modal-deadline-badge').innerHTML.includes('Today'));
assert.equal(timers.at(-1).delay,86400000);
assert.ok($('#src').textContent.includes('Deadline dates use UTC'));
clock = Date.parse('2026-10-07T12:00:00Z');
handlers.visibilitychange();
assert.equal($('#modal-deadline-status').textContent,'Closed');
assert.deepEqual(rendered,[2]);
assert.equal(timers.at(-1).delay,43200000);
const scheduled = timers.length;
document.hidden = true;
handlers.visibilitychange();
assert.equal(timers.length,scheduled);
handlers.focus();
assert.equal(timers.length,scheduled+1);
assert.equal(intervals[0].delay,60000);
clock = Date.parse('2026-10-08T12:00:00Z');
intervals[0].fn();
assert.ok($('#health-dot').className.includes('stale'));
assert.ok($('#health-label').textContent.includes('Pipeline run'));
assert.ok($('#src').textContent.includes('4d old'));
const priorTimers = timers.length;
clock += 60000;
intervals[0].fn();
assert.equal(timers.length,priorTimers);
listings = [];
draw();
assert.equal($('#count-all').textContent,0);
assert.equal($('#count-soon').textContent,0);
console.log(JSON.stringify({refreshed:true}));
""", lifecycle=True)
    assert result['refreshed']
    page = Path('docs/index.html').read_text(encoding='utf-8')
    export = page.split("$('#export-csv-btn').onclick", 1)[1].split('// Load Listings Data', 1)[0]
    assert export.index('draw()') < export.index('selectListingRows(')


@pytest.mark.parametrize(('deadline', 'expected'), [
    ('2026-10-06T00:00:00Z', 1), ('2026-10-05T00:00:00Z', 0),
    ('2026-10-04T23:59:59Z', -1), ('2026-10-06T00:00:00+05:30', 0), (None, None),
])
def test_export_uses_the_same_utc_calendar_day_policy(monkeypatch, deadline, expected):
    monkeypatch.setattr(state, 'utcnow', lambda: datetime(2026, 10, 5, 23, 59, tzinfo=UTC))
    row = defaultdict(lambda: None, id=1, deadline=deadline)
    assert state._public_record(row)['days_left'] == expected


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for dashboard verification')
def test_complete_dashboard_scripts_parse_without_command_line_size_limits():
    page = Path('docs/index.html').read_text(encoding='utf-8')
    scripts = re.findall(r'<script>(.*?)</script>', page, re.S)
    assert len(scripts) == 2
    for script in scripts:
        subprocess.run(
            [shutil.which('node'), '-e', "new Function(require('fs').readFileSync(0,'utf8'));"],
            input=script, check=True, capture_output=True, text=True, encoding='utf-8',
        )
