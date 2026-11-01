/** Realistic Cloudflare subscriber result regressions. No Telegram API or provider egress. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {panel, subscriberUpdate} from './subscribers.mjs';

const isoDaysAgo = days => new Date(Date.now() - days * 86400000).toISOString();
const preferences = () => ({
  topics: {predoc: isoDaysAgo(100), data_analyst: isoDaysAgo(100)},
  scopes: {remote: isoDaysAgo(100)}, paused: false, language: 'en',
  delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC',
});
function academic(days, suffix = 'a', other = {}) {
  // This matches the real Python cloud snapshot: first_seen_at and
  // last_seen_at are present, published_at used to be absent.
  return {url_hash: suffix.repeat(64), kind: 'predoc', title: 'Research Assistant ' + suffix,
    institution: 'University', apply_url: 'https://example.edu/jobs/' + suffix,
    first_seen_at: isoDaysAgo(days), last_seen_at: isoDaysAgo(1),
    closed_at: null, expired_at: null, deadline: null, ...other};
}
function fixture({rows = [], career = [], member = preferences(), snapshot = isoDaysAgo(0)} = {}) {
  const values = new Map([['subscribers_initialized', true], ['subscriber:42', member],
    ['career_listings', career]]);
  if (snapshot) values.set('snapshot_at', snapshot);
  const sent = [];
  const storage = {
    get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k),
    transaction: async callback => callback(storage),
  };
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''},
    api: async () => {}, dataset: async () => ({rows, marks: new Map()}),
    deliver: async (_key, _method, content) => {sent.push(content);}};
  const msg = {chat: {id: 42, type: 'private'}, message_id: 9};
  const tap = async (raw, key = raw) => {
    await subscriberUpdate(bot, msg, {data: raw, id: key}, 'test:' + key);
    return sent.at(-1);
  };
  return {tap, sent, values};
}

test('academic match is shown when cloud snapshot has first_seen_at but no published_at', async () => {
  const f = fixture({rows: [academic(6), academic(20, 'b')]});
  const shown = await f.tap('sub:p:latest:7:0');
  assert.match(shown.text, /Research Assistant a/);
  assert.doesNotMatch(shown.text, /Research Assistant b/);
  assert.match(shown.text, /https:\/\/example.edu\/jobs\/a/);
});

test('settings exposes a saved history window without changing subscriber alert preferences', async () => {
  assert.ok(panel(preferences(), 'more').reply_markup.inline_keyboard.flat().some(
    b => b.callback_data === 'sub:p:history'));
  const f = fixture({rows: [academic(80), academic(95, 'b')]});
  const storedBefore = structuredClone(f.values.get('subscriber:42'));
  const setting = await f.tap('sub:w:90');
  assert.equal(f.values.get('match_window:42'), 90);
  assert.match(setting.text, /3 months|90 days/i);
  assert.deepEqual(f.values.get('subscriber:42'), storedBefore);
  const reopened = await f.tap('sub:p:latest', 'reopen');
  assert.match(reopened.text, /Research Assistant a/);
  assert.doesNotMatch(reopened.text, /Research Assistant b/);
  const override = await f.tap('sub:p:latest:7:0', 'override');
  assert.doesNotMatch(override.text, /Research Assistant a/);
  assert.equal(f.values.get('match_window:42'), 90);
  await f.tap('sub:stop:yes', 'unsubscribe');
  assert.equal(f.values.has('match_window:42'), false);
});

test('date-only deadline does not hide a role at UTC midnight of its deadline day', async () => {
  const deadline = new Date().toISOString().slice(0, 10);
  const f = fixture({rows: [academic(1, 'a', {deadline})]});
  assert.match((await f.tap('sub:p:latest:7:0')).text, /Research Assistant a/);
});

test('untrusted or malformed job links never enter Telegram HTML result markup', async () => {
  const f = fixture({rows: [
    academic(1, 'a', {apply_url: 'javascript:alert(1)'}),
    academic(1, 'b', {apply_url: 'https://user:pass@example.edu/jobs/b'}),
    academic(1, 'c'),
  ]});
  const text = (await f.tap('sub:p:latest:7:0')).text;
  assert.match(text, /Research Assistant c/);
  assert.doesNotMatch(text, /Research Assistant a|Research Assistant b|javascript:|user:pass/);
});

test('missing snapshot yields an actionable connection warning instead of implying no vacancies', async () => {
  const f = fixture({snapshot: null});
  const text = (await f.tap('sub:p:latest')).text;
  assert.match(text, /listing snapshot.*not.*sync|sync.*snapshot/i);
});

test('career result with unknown availability is visibly unverified', async () => {
  const f = fixture({career: [{category: 'data_analyst', scope: 'remote',
    title: 'Data analyst', employer: 'Example Research Lab',
    url: 'https://example.org/job/42', first_seen_at: isoDaysAgo(2),
    availability: 'unknown'}]});
  const text = (await f.tap('sub:p:latest:7:0')).text;
  assert.match(text, /Data analyst/);
  assert.match(text, /[Uu]nverified|not verified/);
});
