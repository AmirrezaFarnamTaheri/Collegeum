/** Worker status exposes specialist counts without breaking legacy total consumers. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {TelegramBot} from './worker.mjs';

class Storage {
  values = new Map();
  async get(key) { return structuredClone(this.values.get(key)); }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
  async delete(key) { this.values.delete(key); }
  async list({prefix} = {}) {
    return new Map([...this.values].filter(([key]) => !prefix || key.startsWith(prefix)));
  }
  async transaction(fn) { return fn(this); }
}

test('synced health counts general Career and Life Sciences separately', async () => {
  const storage = new Storage();
  const bot = new TelegramBot({storage}, {});
  const now = new Date().toISOString();
  const careers = [
    ...Array.from({length: 88}, (_, i) => ({
      category: 'life_sciences_phd', scope: '', first_seen_at: now,
      title: 'Life Sciences PhD ' + i, employer: 'University',
      url: 'https://example.edu/phd/' + i,
    })),
    ...Array.from({length: 2}, (_, i) => ({
      category: 'data_analyst', scope: 'remote', first_seen_at: now,
      title: 'Data Analyst ' + i, employer: 'Employer',
      url: 'https://example.edu/job/' + i,
    })),
  ];
  const response = await bot.sync({listings: [], career_listings: careers,
    generated_at: now, subscriber_protocol: 1, subscribers: {}});
  assert.equal(response.status, 200);
  assert.deepEqual(await storage.get('snapshot_counts'), {
    academic: 0, career: 90, general_career: 2, life_sciences_phd: 88,
  });
});
