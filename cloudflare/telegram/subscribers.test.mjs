import assert from 'node:assert/strict';
import test from 'node:test';
import {panel, validPreferences, matchesPreferences, pageSize, subscriberUpdate} from './subscribers.mjs';

const member = {topics: {predoc: new Date().toISOString()}, scopes: {}, paused: false,
  language: 'en', delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC'};

test('both languages keep all settings reachable with bounded native buttons', () => {
  for (const language of ['en', 'fa']) {
    for (const page of ['home', 'academic', 'careers', 'life_sciences', 'markets',
      'delivery', 'more', 'help', 'privacy', 'stop']) {
      const result = panel({...member, language}, page);
      assert.ok(result.text.length < 4096);
      if (language === 'fa') assert.match(result.text, /[\u0600-\u06ff]/);
      for (const row of result.reply_markup.inline_keyboard) {
        assert.ok(row.length <= 2);
        for (const button of row) assert.ok(Buffer.byteLength(button.callback_data) <= 64);
      }
      if (page !== 'home') assert.ok(result.reply_markup.inline_keyboard.flat().some(b => b.callback_data === 'sub:p:home'));
    }
  }
  assert.ok(panel(member).reply_markup.inline_keyboard.length <= 4);
  assert.match(panel(null).text, /Choose roles/);
  assert.ok(panel(member, 'more').reply_markup.inline_keyboard.flat().some(b => b.callback_data === 'sub:p:stop'));
});

test('subscriber schema rejects receipts, invalid controls and unknown topics', () => {
  assert.equal(validPreferences(member), true);
  assert.equal(validPreferences(null), true);
  for (const invalid of [{...member, deliveries: {}}, {...member, topics: {unknown: 'now'}},
    {...member, daily_limit: true}, {...member, paused: 'false'}, {...member, timezone: 'fake'},
    {...member, scopes: []}]) assert.equal(validPreferences(invalid), false);
});

test('listings respect saved topics and career markets, including empty selections', () => {
  assert.equal(matchesPreferences({kind: 'predoc'}, member), true);
  assert.equal(matchesPreferences({kind: 'phd'}, member), false);
  assert.equal(matchesPreferences({kind: 'predoc'}, {...member, topics: {}}), false);
  assert.equal(matchesPreferences({kind: 'predoc'}, null), false);
  const career = {...member, topics: {data_analyst: '2026-10-16'}, scopes: {remote: '2026-10-16'}};
  assert.equal(matchesPreferences({category: 'data_analyst', scope: 'iran'}, career), false);
  assert.equal(matchesPreferences({category: 'data_analyst', scope: 'remote'}, career), true);
  assert.equal(pageSize(999), 4);
});

test('page size persists, paginates filtered matches and survives duplicate callbacks', async () => {
  const values = new Map([['subscribers_initialized', true], ['subscriber:42', member]]);
  const storage = {get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)), delete: async k => values.delete(k),
    transaction: async fn => fn(storage)};
  const sent = [];
  const bot = {ctx: {storage}, api: async () => {}, deliver: async (key, method, content) => sent.push(content),
    dataset: async () => ({rows: Array.from({length: 15}, (_, i) => ({kind: i === 14 ? 'phd' : 'predoc',
      title: `Position ${i}`, institution: 'University', apply_url: `https://example.org/${i}`,
      published_at: new Date().toISOString()}))})};
  const message = {chat: {id: 42}, message_id: 1};
  await subscriberUpdate(bot, message, {data: 'sub:n:next'}, 'size');
  await subscriberUpdate(bot, message, {data: 'sub:n:next'}, 'size');
  assert.equal(values.get('page_size:42'), 6);
  await subscriberUpdate(bot, message, {data: 'sub:p:latest:1'}, 'browse');
  assert.equal((sent.at(-1).text.match(/<a href=/g) || []).length, 6);
  assert.doesNotMatch(sent.at(-1).text, /Position 14/);
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b => b.text === '2/3'));
  await subscriberUpdate(bot, message, {data: 'sub:stop:yes'}, 'stop');
  assert.equal(values.has('page_size:42'), false);
});
