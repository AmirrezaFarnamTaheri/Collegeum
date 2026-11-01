/** User-facing cached counts must not treat Life Sciences PhDs as general Career jobs. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {subscriberUpdate} from './subscribers.mjs';

const at = new Date().toISOString();
const member = {
  topics: {data_analyst: at, life_sciences_phd: at},
  scopes: {remote: at}, academic_regions: {}, paused: false,
  language: 'en', delivery_mode: 'instant', daily_limit: 6,
  quiet_hours: false, timezone: 'UTC',
};
function fixture(language) {
  const jobs = [
    ...Array.from({length: 88}, (_, i) => ({
      category: 'life_sciences_phd', title: 'PhD ' + i,
      employer: 'University', first_seen_at: at,
      url: 'https://example.edu/phd/' + i, availability: 'unknown',
    })),
    ...Array.from({length: 2}, (_, i) => ({
      category: 'data_analyst', scope: 'remote', title: 'Analyst ' + i,
      employer: 'Employer', first_seen_at: at,
      url: 'https://example.edu/jobs/' + i, availability: 'unknown',
    })),
  ];
  const values = new Map([
    ['subscribers_initialized', true],
    ['subscriber:42', {...member, language}],
    ['career_listings', jobs],
    ['snapshot_at', at],
  ]);
  const sent = [];
  const storage = {
    get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k),
    transaction: async fn => fn(storage),
  };
  const bot = {
    ctx: {storage}, env: {OWNER_IDS: ''}, api: async () => {},
    dataset: async () => ({rows: [], marks: new Map()}),
    deliver: async (_key, _method, content) => sent.push(content),
  };
  return {bot, sent};
}

test('English matches distinguish 2 general Career from 88 specialist PhD records', async () => {
  const {bot, sent} = fixture('en');
  await subscriberUpdate(bot, {chat: {id: 42, type: 'private'}, message_id: 1},
    {data: 'sub:p:latest:7:0', id: 'en-counts'}, 'en-counts');
  assert.match(sent.at(-1).text, /2 career jobs.*88 Life Sciences PhDs/i);
  assert.doesNotMatch(sent.at(-1).text, /90 career records/i);
});

test('Persian matches distinguish general Career from specialist PhD records', async () => {
  const {bot, sent} = fixture('fa');
  await subscriberUpdate(bot, {chat: {id: 42, type: 'private'}, message_id: 1},
    {data: 'sub:p:latest:7:0', id: 'fa-counts'}, 'fa-counts');
  assert.match(sent.at(-1).text, /2 شغل عمومی.*88 فرصت دکتری علوم زیستی/);
});
