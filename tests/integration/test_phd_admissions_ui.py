"""Execute admissions count, filters and cards with the same evidence clock."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_admissions(assertions: str) -> None:
    page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    source = page.split("// Programme admissions are NEVER merged", 1)[1]
    source = "// Programme admissions are NEVER merged" + source.split(
        "    fetch('data/phd_admissions.json'", 1,
    )[0]
    setup = """
const assert = require('node:assert/strict');
let clock = Date.parse('2026-11-24T12:00:00Z');
Date.now = () => clock;
const nodes = new Map();
const $ = id => {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', textContent: '', innerHTML: '', hidden: false, handlers: {},
    querySelectorAll() { return []; },
    addEventListener(event, handler) { this.handlers[event] = handler; }
  });
  return nodes.get(id);
};
const esc = text => String(text).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const row = {
  institution: 'Current University', country_code: 'US', status: 'verified',
  deadline_iso: '2027-01-15', checked_at: '2026-11-24T11:00:00Z',
  official_programme_url: 'https://www.example.edu/economics/phd',
  evidence_url: 'https://example.edu/economics/admissions',
  evidence_excerpt: 'PhD Economics application deadline: January 15, 2027',
  investigated_urls: ['https://example.edu/economics/admissions']
};
"""
    result = subprocess.run([shutil.which("node")], input=setup + source + assertions,
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


@unittest.skipUnless(shutil.which("node"), "Node is needed to execute dashboard functions")
class AdmissionsUiTests(unittest.TestCase):
    def test_summary_filter_and_cards_agree_and_remove_expired_evidence(self):
        run_admissions("""
phdAdmissions = [row,
  {...row, institution: 'Stale University', checked_at: '2026-11-01T11:00:00Z'},
  {...row, institution: 'Future Check University', checked_at: '2026-11-25T11:00:00Z'},
  {...row, institution: 'No Evidence University', evidence_excerpt: ''},
  {...row, institution: 'Bad Date University', deadline_iso: '2027-02-30'},
  {...row, institution: 'Yearless University', status: 'no_explicit_deadline', deadline_iso: null},
];
renderAdmissions();
assert.equal($('#phd-admissions-summary').textContent, '6 programmes · 1 verified deadline');
const dates = $('#phd-admissions-results').innerHTML.match(/<time datetime=/g) || [];
assert.equal(dates.length, 1);
assert.match($('#phd-admissions-results').innerHTML, /datetime="2027-01-15">15 Jan 2027/);
$('#phd-admissions-status').value = 'verified';
renderAdmissions();
assert.equal($('#phd-admissions-summary').textContent, '1 programme · 1 verified deadline');
assert.match($('#phd-admissions-results').innerHTML, /Current University/);
assert.doesNotMatch($('#phd-admissions-results').innerHTML, /Stale University/);
$('#phd-admissions-status').value = 'unverified';
renderAdmissions();
assert.equal($('#phd-admissions-summary').textContent, '5 programmes · 0 verified deadlines');
assert.doesNotMatch($('#phd-admissions-results').innerHTML, /<time datetime=/);
clock = Date.parse('2026-12-09T12:00:00Z');
$('#phd-admissions-status').value = 'verified';
renderAdmissions();
assert.equal($('#phd-admissions-summary').textContent, '0 programmes · 0 verified deadlines');
""")

    def test_invalid_provenance_and_dates_cannot_be_confirmed(self):
        run_admissions("""
assert.equal(admissionsDeadlineConfirmed(row), true);
const invalid = [
  {deadline_iso: '20270115'}, {deadline_iso: '2027-02-30'},
  {deadline_iso: '2026-11-23'}, {deadline_iso: '2030-01-15'},
  {checked_at: '2026-11-24'}, {checked_at: '2026-11-24T11:00:00'},
  {checked_at: '2026-11-25T11:00:00Z'}, {checked_at: '2026-11-10T11:59:59Z'},
  {evidence_excerpt: 'Application deadline January 15'},
  {evidence_excerpt: 'Application deadline January 14, 2027'},
  {evidence_excerpt: '<script>alert(1)</script>'},
  {evidence_url: 'http://example.edu/economics/admissions'},
  {evidence_url: 'https://example.edu.evil.test/economics/admissions'},
  {evidence_url: 'https://example.edu:444/economics/admissions'},
  {evidence_url: 'https://user:pass@example.edu/economics/admissions'},
  {investigated_urls: []}, {status: 'ambiguous_deadline'},
];
for (const change of invalid) assert.equal(admissionsDeadlineConfirmed({...row, ...change}), false,
                                          JSON.stringify(change));
assert.equal(admissionsDeadlineConfirmed({...row, checked_at: '2026-11-10T12:00:00Z'}), true);
assert.equal(admissionsDeadlineConfirmed({...row, deadline_iso: '2026-11-24',
  evidence_excerpt: 'Deadline 24 November 2026'}), true);
assert.equal(admissionsDeadlineConfirmed({...row, deadline_iso: '2027-04-03',
  evidence_excerpt: 'Deadline 03/04/2027'}), false);
assert.equal(admissionsDeadlineConfirmed({...row, checked_at: '2026-11-31T11:00:00Z'},
  Date.parse('2026-12-02T12:00:00Z')), false);
assert.equal(admissionsDeadlineConfirmed({...row, checked_at: '2026-11-23T24:00:00Z'}), false);
assert.equal(admissionsDeadlineConfirmed({...row, checked_at: '2026-11-24T14:30:00+03:30'}), true);
""")

    def test_open_page_expires_evidence_without_rebuilding_unchanged_cards(self):
        run_admissions("""
$('#phd-admissions-summary').textContent = 'Loading programmes…';
refreshAdmissionsEvidence();
assert.equal($('#phd-admissions-summary').textContent, 'Loading programmes…');
phdAdmissions = [{...row, checked_at: '2026-11-10T12:00:00Z'}];
renderAdmissions();
assert.equal($('#phd-admissions-summary').textContent, '1 programme · 1 verified deadline');
const cards = $('#phd-admissions-results');
let writes = 0, markup = cards.innerHTML;
Object.defineProperty(cards, 'innerHTML', {
  get() { return markup; }, set(value) { writes++; markup = value; }
});
refreshAdmissionsEvidence();
assert.equal(writes, 0);
clock += 1;
refreshAdmissionsEvidence();
assert.equal(writes, 1);
assert.equal($('#phd-admissions-summary').textContent, '1 programme · 0 verified deadlines');
assert.doesNotMatch(cards.innerHTML, /<time datetime=/);
clock += 60000;
refreshAdmissionsEvidence();
assert.equal(writes, 1);
""")

    def test_all_stored_verified_layouts_still_render_when_fresh(self):
        public = json.loads((ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8"))
        run_admissions("phdAdmissions = " + json.dumps(public["programmes"]) + ";\n" + """
for (const original of phdAdmissions.filter(item => item.status === 'verified')) {
  // Isolate formatting from the passage of wall-clock time and future refreshes.
  const checked = Date.parse(original.checked_at);
  const now = Math.max(checked, Date.parse('2026-11-24T12:00:00Z'));
  assert.equal(admissionsDeadlineConfirmed(original, now), true, original.institution);
}
""")

    def test_shows_applicant_scope_and_required_earlier_stage_with_the_date(self):
        run_admissions(r"""
phdAdmissions = [{...row, deadline_iso: '2027-03-31',
  evidence_excerpt: 'GPEM Doctoral Program (Foreign Student Screening): ' +
    'Application Period ends March 31, 2027; ' +
    'required Pre application ends February 15, 2027. <script>unsafe()</script>'}];
renderAdmissions();
const card = $('#phd-admissions-results').innerHTML;
assert.match(card, /datetime="2027-03-31">31 Mar 2027/);
assert.match(card, /<details class="admissions-details"/);
assert.doesNotMatch(card, /<details[^>]+\sopen[\s=>]/);
assert.match(card, /Foreign Student Screening/);
assert.match(card, /required Pre application ends February 15, 2027/);
const visible = card.replace(/<details[\s\S]*?<\/details>/g, '');
assert.match(visible, /Foreign Student Screening/);
assert.match(visible, /required Pre application ends February 15, 2027/);
assert.match(card, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
assert.doesNotMatch(card, /<script>/);
phdAdmissions[0].status = 'ambiguous_deadline';
renderAdmissions();
assert.doesNotMatch($('#phd-admissions-results').innerHTML, /Admission details/);
""")

    def test_paging_search_and_deadline_order_use_the_actual_controls(self):
        run_admissions(r"""
phdAdmissions = Array.from({length: 25}, (_, index) => ({...row,
  institution: 'University ' + String(index).padStart(2, '0'),
  status: index < 5 ? 'no_explicit_deadline' : 'verified'}));
phdAdmissions[24] = {...row, institution: 'Closing first',
  deadline_iso: '2026-12-01', evidence_excerpt: 'Deadline December 1, 2026'};
renderAdmissions();
let cards = $('#phd-admissions-results').innerHTML;
assert.equal((cards.match(/<article/g) || []).length, 12);
assert.ok(cards.indexOf('Closing first') < cards.indexOf('University 05'));
assert.doesNotMatch(cards, /University 00/);
assert.equal($('#phd-admissions-more').hidden, false);
$('#phd-admissions-results').querySelectorAll = () => [{dataset: {programme: 'US|Closing first'}}];
$('#phd-admissions-more').onclick();
assert.equal(($('#phd-admissions-results').innerHTML.match(/<article/g) || []).length, 24);
assert.match($('#phd-admissions-results').innerHTML, /data-programme="US\|Closing first" open>/);
$('#phd-admissions-search').value = 'University 0';
$('#phd-admissions-search').handlers.input();
assert.equal(phdAdmissionsLimit, 12);
assert.equal($('#phd-admissions-summary').textContent, '10 programmes · 5 verified deadlines');
assert.equal($('#phd-admissions-more').hidden, true);
assert.doesNotMatch($('#phd-admissions-more').textContent, /-\d+/);
$('#phd-admissions-status').value = 'unverified';
$('#phd-admissions-status').handlers.input();
assert.equal($('#phd-admissions-summary').textContent, '5 programmes · 0 verified deadlines');
assert.doesNotMatch($('#phd-admissions-results').innerHTML, /<time datetime=/);
""")

    def test_entry_route_is_visible_and_hidden_paging_is_not_overridden(self):
        page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn(".admissions-more[hidden] { display: none; }", page)
        run_admissions(r"""
phdAdmissions = [{...row, official_details: {admission_route: {
  value: "Master's-stage entry; doctoral continuation requires separate admission",
  checked_at: row.checked_at, evidence_url: row.evidence_url,
  evidence_excerpt: 'Official doctoral entry route'
}}}];
renderAdmissions();
const visible = $('#phd-admissions-results').innerHTML.replace(/<details[\s\S]*?<\/details>/g, '');
assert.match(visible,
  /Master&#39;s-stage entry; doctoral continuation requires separate admission/);
assert.equal($('#phd-admissions-more').hidden, true);
clock = Date.parse('2026-12-09T12:00:00Z');
renderAdmissions();
assert.doesNotMatch($('#phd-admissions-results').innerHTML, /Master&#39;s-stage/);
""")

    def test_full_year_french_and_parenthesized_weekdays_keep_original_evidence(self):
        run_admissions("""
const cases = [
  ['2027-02-01', "Déposer la demande d'admission Du 1 er août 2026 au 1 er février 2027"],
  ['2026-12-24', 'Applications close on December 24 (Thu), 2026'],
  ['2027-03-11', 'Application documents and fee: March 11 (1pm/Thurs) 2027'],
  ['2027-01-15', 'Application Deadline: 15 janvier 2027'],
  ['2027-03-15', 'Application Deadline: 15 mars 2027'],
  ['2027-04-15', 'Application Deadline: 15 avril 2027'],
  ['2027-05-15', 'Application Deadline: 15 mai 2027'],
  ['2027-06-15', 'Application Deadline: 15 juin 2027'],
  ['2027-07-15', 'Application Deadline: 15 juillet 2027'],
  ['2027-08-15', 'Application Deadline: 15 août 2027'],
  ['2027-09-15', 'Application Deadline: 15 septembre 2027'],
  ['2027-10-15', 'Application Deadline: 15 octobre 2027'],
  ['2027-11-15', 'Application Deadline: 15 novembre 2027'],
  ['2026-12-15', 'Application Deadline: 15 décembre 2026'],
];
for (const [deadline_iso, evidence_excerpt] of cases) {
  assert.equal(admissionsDeadlineConfirmed({...row, deadline_iso, evidence_excerpt}), true,
    evidence_excerpt);
}
assert.equal(admissionsDeadlineConfirmed({...row, deadline_iso: '2027-02-01',
  evidence_excerpt: "Date limite: 1 er février"}), false);
""")


if __name__ == "__main__":
    unittest.main()
