"""Execute the webpage's actual health presentation function in Node."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed for the webpage checks")
def test_web_health_never_marks_fatal_incomplete_or_unknown_data_green():
    page = Path("docs/index.html").read_text(encoding="utf-8")
    start = page.split("function healthPresentation", 1)[1]
    function = "function healthPresentation" + start.split(
        "// Health Telemetry", 1
    )[0]
    script = function + """
const assert = require('node:assert/strict');
const now = Date.parse('2026-10-05T12:00:00Z');
const fresh = { generated_at: '2026-10-05T11:00:00Z' };
const cases = [
  [{...fresh, status: 'fatal'}, 'dead', 'Pipeline failed'],
  [{...fresh, status: 'quota-stopped'}, 'stale', 'request limit'],
  [{...fresh, status: 'degraded', source_summary: {failed: 2}}, 'stale', '2 source checks failed'],
  [{...fresh, last_run: {outcome: 'partial'}}, 'stale', 'incomplete'],
  [{...fresh, last_run: {outcome: 'ok', errors: 1}}, 'stale', 'incomplete'],
  [{...fresh, runs: [{outcome: 'ok', source_stats: {a: {ok: false}}}]},
    'stale', '1 source checks failed'],
  [{...fresh, status: 'ok'}, '', 'Pipeline active'],
  [{...fresh, status: 'ok', runs: [{source_stats: {a: {skipped: true, errors: 1}}}]},
    '', 'Pipeline active'],
  [{...fresh, status: 'ok', runs: [{finished_at: '2026-10-01T12:00:00Z'}]}, 'dead', 'delayed'],
  [{...fresh, status: 'ok', runs: [{finished_at: '2026-10-04T10:00:00Z'}]},
    'stale', 'Pipeline run'],
  [{...fresh}, 'stale', 'unavailable'],
  [{status: 'ok', generated_at: 'invalid'}, 'stale', 'unavailable'],
  [{status: 'ok', generated_at: '2026-10-06T12:00:00Z'}, 'stale', 'unavailable'],
  [{}, 'stale', 'unavailable']
];
for (const [data, cls, label] of cases) {
  const result = healthPresentation(data, now);
  assert.equal(result.cls, cls);
  assert.ok(result.label.includes(label), JSON.stringify(result));
}
"""
    subprocess.run([shutil.which("node"), "-e", script], check=True,
                   capture_output=True, text=True)
