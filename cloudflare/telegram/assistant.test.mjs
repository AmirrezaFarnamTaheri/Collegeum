import assert from 'node:assert/strict';
import test from 'node:test';
import {ask, openrouterKeys, queryRecords, refusal, renderAnswer, validateQuery} from './assistant.mjs';

const row = {id:42, url_hash:'a'.repeat(64), title:'<script>Economics RA</script>', institution:'Example',
  apply_url:'https://example.org/job', country:'Canada', kind:'predoc', visa:'unknown'};

test('query grammar rejects SQL, unknown tools and impossible dates', () => {
  assert.throws(() => validateQuery({action:'list',sql:'SELECT * FROM meta'}));
  assert.throws(() => validateQuery({action:'shell'}));
  assert.throws(() => validateQuery({action:'list',deadline_before:'2026-02-30'}));
  assert.throws(() => validateQuery({action:'list',limit:10000}));
});

function instance(keys = 'a,b') {
  const values = new Map();
  return {
    env: {OPENROUTER_API_KEYS: keys},
    ctx: {storage: {
      async get(key) { return values.get(key); },
      async put(key, value) { values.set(key, value); },
      async list({prefix}) { return new Map([...values].filter(([key]) => key.startsWith(prefix))); },
    }},
    async dataset() { return {rows: [row], marks: new Map()}; },
  };
}

test('key formats and ordered deduplication match Python configuration', () => {
  for (const additional of ['first,second', ' first; second\n', '["first", "second"]',
    ['first', 'second']]) {
    assert.deepEqual(openrouterKeys({OPENROUTER_API_KEYS: additional,
      OPENROUTER_API_KEY: 'second, third'}), ['first', 'second', 'third']);
  }
  assert.deepEqual(openrouterKeys({OPENROUTER_API_KEY: 'first; second'}), ['first', 'second']);
  assert.deepEqual(openrouterKeys({OPENROUTER_API_KEYS: '[]'}), []);
  assert.deepEqual(openrouterKeys({OPENROUTER_API_KEYS: ' , ;\n'}), []);
  assert.deepEqual(openrouterKeys({}), []);
});

test('JSON array credentials reach the provider without quotes or duplicate attempts', async () => {
  const original = globalThis.fetch;
  const credentials = [];
  globalThis.fetch = async (_url, options) => {
    credentials.push(options.headers.Authorization);
    if (credentials.length < 3) return new Response('', {status: 429});
    return Response.json({choices: [{message: {tool_calls: [{function: {
      name: 'query_database', arguments: '{"action":"count"}',
    }}]}}]});
  };
  try {
    const bot = instance('["first", "second", "first"]');
    bot.env.OPENROUTER_API_KEY = 'second, third';
    const answer = await ask(bot, 'Count roles', 42, true);
    assert.match(answer, /1 matching record/);
    assert.deepEqual(credentials, ['Bearer first', 'Bearer second', 'Bearer third']);
  } finally { globalThis.fetch = original; }
});

test('invalid key arrays are unavailable without sending manufactured credentials', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('must not call provider'); };
  try {
    for (const invalid of ['["first", "second"', '[first]', '["first", null]',
      '["first", 42]', '["first", true]', '["first", {"key":"second"}]',
      '["first", ["second"]]', ['first', null], ['first', 42], {key: 'first'}]) {
      const bot = instance(invalid);
      bot.env.OPENROUTER_API_KEY = 'valid-single';
      const answer = await ask(bot, 'Count roles', 42, true);
      assert.match(answer, /temporarily unavailable/);
    }
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test('provider transport failure rotates keys and preserves a grounded answer', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    if (++calls === 1) throw new Error('network unavailable');
    return Response.json({choices: [{message: {tool_calls: [{function: {
      name: 'query_database', arguments: '{"action":"count"}',
    }}]}}]});
  };
  try {
    const answer = await ask(instance(), 'Count roles', 42, true);
    assert.equal(calls, 2);
    assert.match(answer, /1 matching record/);
  } finally { globalThis.fetch = original; }
});

test('provider outage and invalid provider JSON are unavailable, not scoped refusals', async () => {
  const original = globalThis.fetch;
  try {
    for (const provider of [async () => { throw new Error('timeout'); },
      async () => new Response('invalid JSON', {status: 200}),
      async () => Response.json(null), async () => Response.json({choices: []})]) {
      globalThis.fetch = provider;
      const answer = await ask(instance(), 'Count roles', 42, true);
      assert.notEqual(answer, refusal);
      assert.match(answer, /temporarily unavailable/);
    }
    globalThis.fetch = async () => Response.json({choices: [{message: {tool_calls: [{
      function: {name: 'query_database', arguments: '{"action":"list","sql":"bad"}'},
    }]}}]});
    assert.equal(await ask(instance(), 'Count roles', 42, true), refusal);
  } finally { globalThis.fetch = original; }
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
