import assert from 'node:assert/strict';
import test from 'node:test';
import {panel, validPreferences} from './subscribers.mjs';

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
