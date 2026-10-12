import assert from 'node:assert/strict';
import test from 'node:test';
import {queryRecords, renderAnswer, validateQuery} from './assistant.mjs';

const row = {id:42, url_hash:'a'.repeat(64), title:'<script>Economics RA</script>', institution:'Example',
  apply_url:'https://example.org/job', country:'Canada', kind:'predoc', visa:'unknown'};

test('query grammar rejects SQL, unknown tools and impossible dates', () => {
  assert.throws(() => validateQuery({action:'list',sql:'SELECT * FROM meta'}));
  assert.throws(() => validateQuery({action:'shell'}));
  assert.throws(() => validateQuery({action:'list',deadline_before:'2026-02-30'}));
  assert.throws(() => validateQuery({action:'list',limit:10000}));
});
test('personal marks cannot be retrieved by public users', () => {
  assert.throws(() => queryRecords(validateQuery({action:'list',personal_status:'applied'}),
    [row],new Map([[row.url_hash,'applied']]),false));
});
test('unstated deadline and visa remain unknown; factual answer is escaped', () => {
  const query = validateQuery({action:'list',fields:['visa','salary']});
  const text = renderAnswer(query,queryRecords(query,[row],new Map(),false),'2026-10-12');
  assert.match(text,/unknown/);
  assert.match(text,/Unstated/);
  assert.match(text,/&lt;script&gt;/);
  assert.match(text,/https:\/\/example.org\/job/);
  assert.equal(queryRecords(validateQuery({action:'list',deadline_before:'2099-12-01'}),
    [row],new Map(),false).length,0);
});
