import assert from 'node:assert/strict';
import test from 'node:test';
import {openAcademicListing, visibleAcademicMatch} from './subscribers.mjs';

const now = Date.parse('2026-11-03T00:00:00Z');
const member = {topics: {predoc: '2026-10-03T00:00:00Z'},
  scopes: {}, academic_regions: {}};
const ordinary = {
  kind: 'predoc', country: 'United States', deadline: null,
  closed_at: null, expired_at: null, reviewed_public_mirror: false,
};
const mirror = {...ordinary, reviewed_public_mirror: true};

test('confirmed Workday mirror cannot inflate active matches or browsing', () => {
  assert.equal(visibleAcademicMatch(ordinary, member, now), true);
  assert.equal(visibleAcademicMatch(mirror, member, now), false);
  // Do not pretend the historical item is closed or erase existing marks.
  assert.equal(openAcademicListing(mirror, now), true);
});

test('verified alias exclusion does not alter region or deadline guards', () => {
  assert.equal(visibleAcademicMatch({...ordinary, closed_at: '2026-11-01'}, member, now), false);
  assert.equal(visibleAcademicMatch({...ordinary, deadline: '2026-10-28'}, member, now), false);
  assert.equal(visibleAcademicMatch(ordinary,
    {...member, topics: {postdoc: '2026-10-01'}}, now), false);
  assert.equal(visibleAcademicMatch({...ordinary, reviewed_public_mirror: undefined},
    member, now), true);
});
