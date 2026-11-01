/** Regression coverage for larger Telegram result pages. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {PAGE_SIZES, pageSize, panel, subscriberUpdate} from './subscribers.mjs';

const member = {
  topics: {predoc: new Date().toISOString(),
    data_analyst: new Date().toISOString()},
  scopes: {remote: new Date().toISOString()},
  paused: false, language: 'en', delivery_mode: 'instant', daily_limit: 6,
  quiet_hours: false, timezone: 'UTC',
};
const timestamp = () => new Date().toISOString();
const academic = (i, long = false) => ({
  url_hash: i.toString(16).padStart(64, '0'), kind: 'predoc',
  title: long ? 'Research Assistant ' + 'A'.repeat(110) : 'Research Assistant ' + i,
  institution: long ? 'University ' + 'B'.repeat(90) : 'University',
  country: long ? 'C'.repeat(50) : 'Canada',
  first_seen_at: timestamp(), deadline: timestamp().slice(0, 10),
  apply_url: 'https://example.edu/jobs/' + i,
});
const career = i => ({
  category: 'data_analyst', scope: 'remote',
  title: 'Data analyst ' + 'D'.repeat(110),
  employer: 'Laboratory ' + 'E'.repeat(90),
  country: 'F'.repeat(50), first_seen_at: timestamp(),
  deadline: timestamp().slice(0, 10), availability: 'unknown',
  url: 'https://example.edu/careers/' + i,
});
function botFixture(rows, careers = []) {
  const data = new Map([['subscribers_initialized', true], ['subscriber:42', member],
    ['career_listings', careers], ['snapshot_at', timestamp()]]);
  const sent = [];
  const storage = {
    get: async key => structuredClone(data.get(key)),
    put: async (key, value) => data.set(key, structuredClone(value)),
    delete: async key => data.delete(key),
    list: async ({prefix} = {}) => new Map([...data].filter(([key]) =>
      !prefix || key.startsWith(prefix))),
    transaction: async fn => fn(storage),
  };
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''}, api: async () => {},
    deliver: async (_key, _method, content) => sent.push(content),
    dataset: async () => ({rows, marks: new Map()})};
  const message = {chat: {id: 42, type: 'private'}, message_id: 99};
  const tap = async (data, key) => {
    await subscriberUpdate(bot, message, {data, id: key}, key);
    return sent.at(-1);
  };
  return {data, tap};
}
test('display settings offer 4, 6, 8 and 12, never 3', () => {
  assert.deepEqual(PAGE_SIZES, [4, 6, 8, 12]);
  assert.equal(pageSize(12), 12);
  assert.equal(pageSize(3), 4);
  const buttons = panel(member, 'display', 12).reply_markup.inline_keyboard.flat();
  assert.deepEqual(buttons.filter(b => /^sub:n:/.test(b.callback_data))
    .map(b => b.callback_data), ['sub:n:4', 'sub:n:6', 'sub:n:8', 'sub:n:12']);
  assert.ok(buttons.some(b => b.callback_data === 'sub:n:12' &&
    b.text.startsWith('☑')));
});

test('selecting 12 persists and displays 12 academic matches per page', async () => {
  const f = botFixture(Array.from({length: 25}, (_, i) => academic(i)));
  await f.tap('sub:n:12', 'set-size');
  assert.equal(f.data.get('page_size:42'), 12);
  const first = await f.tap('sub:p:latest:14:0', 'first-page');
  assert.equal((first.text.match(/<a href=/g) || []).length, 12);
  assert.ok(first.reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:14:1'));
  const second = await f.tap('sub:p:latest:14:1', 'second-page');
  assert.equal((second.text.match(/<a href=/g) || []).length, 12);
  const last = await f.tap('sub:p:latest:14:2', 'last-page');
  assert.equal((last.text.match(/<a href=/g) || []).length, 1);
  await f.tap('sub:stop:yes', 'delete');
  assert.equal(f.data.has('page_size:42'), false);
});

test('twelve long academic result cards fit the Telegram message limit', async () => {
  const f = botFixture(Array.from({length: 12}, (_, i) => academic(i, true)));
  await f.tap('sub:n:12', 'size');
  const page = await f.tap('sub:p:latest:14:0', 'long-academic');
  assert.equal((page.text.match(/<a href=/g) || []).length, 12);
  assert.ok(page.text.length <= 4096, `page contains ${page.text.length} characters`);
});

test('twelve long career result cards fit the Telegram message limit', async () => {
  const f = botFixture([], Array.from({length: 12}, (_, i) => career(i)));
  await f.tap('sub:n:12', 'size');
  const page = await f.tap('sub:p:latest:14:0', 'long-career');
  assert.equal((page.text.match(/<a href=/g) || []).length, 12);
  assert.ok(page.text.length <= 4096, `page contains ${page.text.length} characters`);
});
