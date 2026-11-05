import assert from 'node:assert/strict';
import test from 'node:test';
import {panel, validPreferences, matchesPreferences, pageSize, subscriberUpdate} from './subscribers.mjs';

const member = {topics: {predoc: new Date().toISOString()}, scopes: {}, paused: false,
  language: 'en', delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC'};

test('both languages keep all settings reachable with bounded native buttons', () => {
  for (const language of ['en', 'fa']) {
    for (const page of ['home', 'subscriptions', 'display', 'academic', 'careers', 'life_sciences', 'markets',
      'delivery', 'more', 'browse', 'account', 'help', 'privacy', 'stop']) {
      const result = panel({...member, language}, page);
      assert.ok(result.text.length < 4096);
      if (language === 'fa') assert.match(result.text, /[\u0600-\u06ff]/);
      for (const row of result.reply_markup.inline_keyboard) {
        assert.ok(row.length <= 2);
        for (const button of row) assert.ok(Buffer.byteLength(button.callback_data) <= 64);
      }
      if (page !== 'home') assert.ok(result.reply_markup.inline_keyboard.flat().some(b => b.text.startsWith('←')));
    }
  }
  assert.ok(panel(member).reply_markup.inline_keyboard.length <= 4);
  assert.match(panel(null).text, /Choose roles/);
  assert.ok(panel(member, 'account').reply_markup.inline_keyboard.flat().some(b => b.callback_data === 'sub:p:stop'));
  assert.ok(!panel(member, 'more').reply_markup.inline_keyboard.flat().some(b => b.callback_data === 'sub:p:stop'));
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
  await subscriberUpdate(bot, message, {data: 'sub:n:6'}, 'size');
  await subscriberUpdate(bot, message, {data: 'sub:n:6'}, 'size');
  assert.equal(values.get('page_size:42'), 6);
  await subscriberUpdate(bot, message, {data: 'sub:p:latest:1'}, 'browse');
  assert.equal((sent.at(-1).text.match(/<a href=/g) || []).length, 6);
  assert.doesNotMatch(sent.at(-1).text, /Position 14/);
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b => b.text === '2/3'));
  await subscriberUpdate(bot, message, {data: 'sub:stop:yes'}, 'stop');
  assert.equal(values.has('page_size:42'), false);
});

test('menu hierarchy groups subscriptions and uses explicit checkbox states', () => {
  const home = panel(member).reply_markup.inline_keyboard.flat().map(b => b.callback_data);
  assert.ok(home.includes('sub:p:subscriptions'));
  assert.ok(!home.includes('sub:p:academic'));
  const roles = panel(member, 'academic').reply_markup.inline_keyboard.flat();
  assert.ok(roles.find(b => b.callback_data === 'sub:t:predoc').text.startsWith('☑ '));
  assert.ok(roles.find(b => b.callback_data === 'sub:t:phd').text.startsWith('☐ '));
  assert.ok(roles.some(b => b.callback_data === 'sub:p:subscriptions'));
  const display = panel(member, 'display', 6).reply_markup.inline_keyboard.flat();
  assert.equal(display.find(b => b.callback_data === 'sub:n:6').text, '☑ 6');
  assert.equal(display.find(b => b.callback_data === 'sub:n:4').text, '☐ 4');
  assert.ok(display.some(b => b.callback_data === 'sub:p:browse'));
});

test('Latest matches offers all five rolling lookbacks with safe filtering', async () => {
  const now = Date.now();
  const at = days => new Date(now - days * 86400000).toISOString();
  const values = new Map([['subscribers_initialized', true], ['subscriber:42',
    {...member, topics: {...member.topics, data_analyst: at(1)}, scopes: {remote: at(1)}}]]);
  const storage = {get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k), transaction: async fn => fn(storage)};
  const rows = [6, 10, 25, 50, 80, 100].map((age, index) => ({
    url_hash: String(index).repeat(64), kind: 'predoc',
    title: `Academic age ${age}`, institution: 'University',
    apply_url: `https://example.org/academic/${age}`, published_at: at(age),
  }));
  rows.push({...rows[0], url_hash: 'b'.repeat(64), kind: 'phd',
    title: 'Wrong topic', published_at: at(1)});
  rows.push({...rows[0], url_hash: 'c'.repeat(64), closed_at: at(1),
    title: 'Closed position'});
  const career = {category: 'data_analyst', scope: 'remote', title: 'Career age 25',
    url: 'https://example.org/career', employer: 'Research Group',
    first_seen_at: at(25), availability: 'open'};
  values.set('page_size:42', 8);
  values.set('career_listings', [career, {...career, scope: 'iran',
    title: 'Wrong market', url: 'https://example.org/iran'}]);
  const sent = [];
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''}, api: async () => {},
    deliver: async (_key, _method, data) => sent.push(data),
    dataset: async () => ({rows, marks: new Map()})};
  const msg = {chat: {id: 42, type: 'private'}, message_id: 5};
  for (const [days, expected] of [[7, 1], [14, 2], [30, 4], [60, 5], [90, 6]]) {
    await subscriberUpdate(bot, msg, {data: `sub:p:latest:${days}:0`}, `lookback:${days}`);
    const view = sent.at(-1);
    assert.equal((view.text.match(/<a href=/g) || []).length, expected, `last ${days} days`);
    assert.match(view.text, new RegExp(`last ${days} days`, 'i'));
    const range = view.reply_markup.inline_keyboard.flat().filter(b =>
      b.callback_data === `sub:p:range:${days}:0`);
    assert.equal(range.length, 1, 'one range button replaces five inline choices');
    await subscriberUpdate(bot, msg, {data: `sub:p:range:${days}:0`}, `chooser:${days}`);
    const choices = sent.at(-1).reply_markup.inline_keyboard.flat();
    assert.ok(choices.some(b =>
      b.callback_data === `sub:p:latest:${days}:0` && b.text.startsWith('☑')));
    assert.doesNotMatch(view.text, /Wrong topic|Wrong market|Closed position|Academic age 100/);
  }
  // The ordinary command remains backward-compatible with the last-14-day default.
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest'}, 'legacy:default');
  assert.match(sent.at(-1).text, /last 14 days/i);
  assert.equal((sent.at(-1).text.match(/<a href=/g) || []).length, 2);
  assert.equal(values.has('match_window:42'), false); // browsing does not change synced preferences
});

test('Latest lookback survives pagination and refuses unapproved windows', async () => {
  const now = Date.now(), at = age => new Date(now - age * 86400000).toISOString();
  const values = new Map([['subscribers_initialized', true], ['subscriber:42', member]]);
  const storage = {get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k), transaction: async fn => fn(storage)};
  const sent = [], rows = Array.from({length: 10}, (_, i) => ({
    kind: 'predoc', url_hash: String(i).repeat(64), title: `Archive match ${i}`,
    institution: 'University', apply_url: `https://example.org/${i}`,
    published_at: at(32 + i),
  }));
  const bot = {ctx: {storage}, env: {}, api: async () => {},
    deliver: async (_key, _method, data) => sent.push(data),
    dataset: async () => ({rows, marks: new Map()})};
  const msg = {chat: {id: 42, type: 'private'}, message_id: 9};
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:90:0'}, 'archive:0');
  assert.equal((sent.at(-1).text.match(/<a href=/g) || []).length, 4);
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:90:1'));
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:90:1'}, 'archive:1');
  const rangeOnSecondPage = sent.at(-1).reply_markup.inline_keyboard.flat().find(b =>
    b.callback_data === 'sub:p:range:90:1');
  assert.ok(rangeOnSecondPage);
  await subscriberUpdate(bot, msg, {data: rangeOnSecondPage.callback_data}, 'archive:range');
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:90:1' && /Back/.test(b.text)));
  assert.equal(values.has('match_window:42'), false);
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:90:1'}, 'archive:return');
  assert.match(sent.at(-1).text, /last 90 days/i);
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b => b.text === '2/3'));
  assert.equal((sent.at(-1).text.match(/<a href=/g) || []).length, 4);
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:999:0'}, 'archive:bad');
  assert.doesNotMatch(sent.at(-1).text, /Latest matches/);
});


test('My matches preserves newest and soonest deadline sorting across ranges and pages', async () => {
  const now = Date.now();
  const iso = days => new Date(now + days * 86400000).toISOString();
  const rows = [
    {kind: 'predoc', url_hash: 'a'.repeat(64), title: 'Newest discovered',
      institution: 'University', apply_url: 'https://example.org/new',
      first_seen_at: iso(0), deadline: iso(30)},
    {kind: 'predoc', url_hash: 'b'.repeat(64), title: 'Middle deadline',
      institution: 'University', apply_url: 'https://example.org/middle',
      first_seen_at: iso(-1), deadline: iso(10)},
    {kind: 'predoc', url_hash: 'c'.repeat(64), title: 'Third deadline',
      institution: 'University', apply_url: 'https://example.org/third',
      first_seen_at: iso(-2), deadline: iso(25)},
    {kind: 'predoc', url_hash: 'd'.repeat(64), title: 'Later deadline',
      institution: 'University', apply_url: 'https://example.org/later',
      first_seen_at: iso(-3), deadline: iso(35)},
    {kind: 'predoc', url_hash: 'e'.repeat(64), title: 'Soonest deadline',
      institution: 'University', apply_url: 'https://example.org/soon',
      first_seen_at: iso(-4), deadline: iso(2)},
  ];
  const values = new Map([['subscribers_initialized', true], ['subscriber:42', member],
    ['page_size:42', 4], ['match_window:42', 60]]);
  const storage = {get: async k => structuredClone(values.get(k)),
    put: async (k, v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k), transaction: async fn => fn(storage)};
  const sent = [];
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''}, api: async () => {},
    deliver: async (_key, _method, data) => sent.push(data),
    dataset: async () => ({rows, marks: new Map()})};
  const msg = {chat: {id: 42, type: 'private'}, message_id: 999};
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:60:0'}, 'recent');
  let view = sent.at(-1);
  assert.ok(view.text.indexOf('Newest discovered') < view.text.indexOf('Middle deadline'));
  assert.doesNotMatch(view.text, /Soonest deadline/);
  assert.ok(view.reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:60:0:d'));
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:60:0:d'}, 'deadline');
  view = sent.at(-1);
  assert.ok(view.text.indexOf('Soonest deadline') < view.text.indexOf('Middle deadline'));
  assert.ok(view.text.indexOf('Middle deadline') < view.text.indexOf('Newest discovered'));
  assert.doesNotMatch(view.text, /Later deadline/);
  const actions = view.reply_markup.inline_keyboard.flat();
  assert.ok(actions.some(b => b.callback_data === 'sub:p:latest:60:1:d'));
  assert.ok(actions.some(b => b.callback_data === 'sub:p:range:60:0:d'));
  assert.ok(actions.some(b => b.callback_data === 'sub:p:latest:60:0'));
  await subscriberUpdate(bot, msg, {data: 'sub:p:range:60:0:d'}, 'deadline:chooser');
  assert.ok(sent.at(-1).reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:30:0:d'));
  await subscriberUpdate(bot, msg, {data: 'sub:p:latest:60:1:d'}, 'deadline:next');
  view = sent.at(-1);
  assert.match(view.text, /Page 2 of 2/);
  assert.match(view.text, /Later deadline/);
  assert.doesNotMatch(view.text, /Soonest deadline/);
  assert.ok(view.reply_markup.inline_keyboard.flat().some(b =>
    b.callback_data === 'sub:p:latest:60:0:d'));
  assert.equal(values.get('match_window:42'), 60);
  assert.equal(values.get('page_size:42'), 4);
});

test('My matches groups sorting and page size while history remains in settings', async () => {
  for (const language of ['en', 'fa']) {
    const values = new Map([['subscribers_initialized', true],
      ['subscriber:42', {...member, language}],
      ['page_size:42', 12], ['match_window:42', 60]]);
    const storage = {get: async k => structuredClone(values.get(k)),
      put: async (k, v) => values.set(k, structuredClone(v)),
      delete: async k => values.delete(k), transaction: async fn => fn(storage)};
    const sent = [];
    const bot = {ctx: {storage}, env: {OWNER_IDS: '42'}, api: async () => {},
      deliver: async (_key, _method, data) => sent.push(data),
      dataset: async () => ({rows: [{
        kind: 'predoc', url_hash: 'a'.repeat(64), title: 'Research assistant',
        institution: 'University', first_seen_at: new Date().toISOString(),
        apply_url: 'https://example.org/academic',
      }], marks: new Map()})};
    await subscriberUpdate(bot, {chat: {id: 42, type: 'private'}, message_id: 5},
      {data: 'sub:p:latest:60:0:d'}, `compact:${language}`);
    const rows = sent.at(-1).reply_markup.inline_keyboard;
    const controls = rows.find(row => row.some(b => b.callback_data === 'sub:p:display'));
    assert.deepEqual(controls.map(b => b.callback_data), [
      'sub:p:latest:60:0', 'sub:p:latest:60:0:d', 'sub:p:display']);
    assert.equal(controls.length, 3);
    assert.match(controls[2].text, /12/);
    const range = rows.filter(row => row.some(b => b.callback_data === 'sub:p:range:60:0:d'));
    assert.equal(range.length, 1, 'only one range-selection row');
    assert.equal(range[0].length, 1, 'range button occupies its own row');
    assert.match(range[0][0].text, language === 'fa' ? /۲ ماه/ : /Last 2 months/);
    assert.ok(rows.flat().every(b => !/^sub:p:latest:(7|14|30|60|90):0:d$/.test(b.callback_data) ||
      controls.includes(b)), 'five range choices should not be shown on My matches');
    assert.ok(rows.flat().every(b => b.callback_data !== 'sub:p:history'));
    await subscriberUpdate(bot, {chat: {id: 42, type: 'private'}, message_id: 5},
      {data: 'sub:p:range:60:0:d'}, `range:${language}`);
    const chooser = sent.at(-1);
    assert.match(chooser.text, language === 'fa' ? /بازه/ : /Choose a range/);
    const choices = chooser.reply_markup.inline_keyboard.flat();
    for (const days of [7, 14, 30, 60, 90]) {
      assert.ok(choices.some(b => b.callback_data === `sub:p:latest:${days}:0:d`),
        `range chooser must show ${days} days with deadline sort`);
    }
    assert.ok(choices.some(b => b.callback_data === 'sub:p:latest:60:0:d'),
      'return to active sort and chosen range');
    assert.ok(choices.some(b => b.callback_data === 'sub:p:history'),
      'saved default remains configurable behind the range panel');
    assert.ok(rows.flat().some(b => b.callback_data === 'sub:p:subscriptions'));
    assert.ok(rows.flat().some(b => b.callback_data === 'view|tracking|0'));
    const settings = panel({...member, language}, 'browse');
    assert.ok(settings.reply_markup.inline_keyboard.flat().some(b =>
      b.callback_data === 'sub:p:history'), 'saved range remains accessible via Browsing');
    assert.equal(values.get('match_window:42'), 60);
    assert.equal(values.get('page_size:42'), 12);
  }
});
