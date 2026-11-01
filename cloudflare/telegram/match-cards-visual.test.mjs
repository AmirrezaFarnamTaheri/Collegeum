/** Findability: position type, counts, and pagination are scannable without opening links. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {subscriberUpdate} from './subscribers.mjs';

test('mixed match pages distinguish academic and career roles with a visible page indicator', async () => {
  const current = new Date().toISOString();
  const member = {
    topics: {predoc: current, data_analyst: current},
    scopes: {remote: current}, paused: false, language: 'en',
    delivery_mode: 'instant', daily_limit: 6, quiet_hours: false,
    timezone: 'UTC',
  };
  const records = Array.from({length: 5}, (_, i) => ({
    url_hash: i.toString(16).padStart(64, '0'), kind: 'predoc',
    title: 'Research Assistant ' + i, institution: 'University',
    country: 'Germany', apply_url: 'https://example.edu/ra/' + i,
    first_seen_at: current,
  }));
  const careers = [{category: 'data_analyst', scope: 'remote',
    title: 'Data Analyst', employer: 'Lab', country: 'Canada',
    availability: 'unknown', url: 'https://example.edu/career',
    first_seen_at: current}];
  const values = new Map([['subscriber:42', member],
    ['subscribers_initialized', true],['snapshot_at', current],
    ['career_listings', careers]]);
  const sent = [];
  const storage = {
    get: async k => structuredClone(values.get(k)),
    put: async (k,v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k),
    list: async ({prefix} = {}) => new Map([...values].filter(([k]) =>
      !prefix || k.startsWith(prefix))),
    transaction: async fn => fn(storage),
  };
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''},
    api: async () => {}, dataset: async () => ({rows: records, marks: new Map()}),
    deliver: async (_key, _method, content) => sent.push(content)};
  const message = {chat: {id: 42, type: 'private'}, message_id: 100};
  await subscriberUpdate(bot, message, {data: 'sub:p:latest:14:0',
    id: 'mix1'}, 'mix1');
  const first = sent.at(-1);
  assert.match(first.text, /🔎 <b>My matches<\/b>/);
  assert.match(first.text, /Page 1 of 2/);
  assert.match(first.text, /🎓 <a href=.*Research Assistant/);
  assert.match(first.text, /🏛 University/);
  await subscriberUpdate(bot, message, {data: 'sub:p:latest:14:1',
    id: 'mix2'}, 'mix2');
  const second = sent.at(-1);
  assert.match(second.text, /Page 2 of 2/);
  assert.match(second.text, /💼 <a href=.*Data Analyst/);
  assert.match(second.text, /Availability unverified/);
  assert.ok(first.text.length <= 4096);
  assert.ok(second.text.length <= 4096);
});
