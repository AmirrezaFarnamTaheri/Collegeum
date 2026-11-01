import assert from 'node:assert/strict';
import test from 'node:test';
import {ACADEMIC_REGIONS, academicRegion, panel, matchesPreferences, validPreferences,
  subscriberUpdate} from './subscribers.mjs';

const fresh = () => ({topics: {predoc: '2026-10-20T00:00:00Z',
  data_analyst: '2026-10-20T00:00:00Z'},
  scopes: {iran: '2026-10-20T00:00:00Z'},
  academic_regions: {}, paused: false, language: 'en',
  delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC'});
const callbacks = page => page.reply_markup.inline_keyboard.flat().map(b => b.callback_data);

test('career roles and markets are one screen; legacy market deep links work', () => {
  const member = fresh();
  assert.ok(callbacks(panel(member, 'subscriptions')).includes('sub:p:careers'));
  assert.ok(!callbacks(panel(member, 'subscriptions')).includes('sub:p:markets'));
  assert.ok(!callbacks(panel(member, 'more')).includes('sub:p:markets'));
  const career = panel(member, 'careers');
  for (const action of ['sub:t:data_scientist', 'sub:t:data_analyst',
    'sub:g:iran', 'sub:g:remote']) assert.ok(callbacks(career).includes(action), action);
  assert.match(career.text, /Career roles.*job markets|Job markets/i);
  assert.deepEqual(callbacks(panel(member, 'markets')), callbacks(career));
});

test('academic screen supports multi-select regions and an explicit worldwide reset', () => {
  const member = fresh();
  assert.ok(ACADEMIC_REGIONS.includes('europe'));
  const screen = panel(member, 'academic');
  for (const region of ACADEMIC_REGIONS)
    assert.ok(callbacks(screen).includes('sub:r:' + region), region);
  assert.ok(callbacks(screen).includes('sub:r:all'));
  assert.match(screen.text, /Academic regions/i);
  assert.match(screen.text, /worldwide|all regions/i);
  assert.ok(screen.reply_markup.inline_keyboard.every(row => row.length <= 2));
  assert.ok(screen.reply_markup.inline_keyboard.flat().every(b =>
    Buffer.byteLength(b.callback_data) <= 64));
});

test('region classifier distinguishes common academic-country aliases and unknowns', () => {
  for (const [country, region] of [
    ['Germany', 'europe'], ['United Kingdom', 'europe'], ['UK', 'europe'],
    ['CH', 'europe'], ['Canada', 'north_america'], ['United States', 'north_america'],
    ['US', 'north_america'], ['Brazil', 'latin_america'], ['Mexico', 'latin_america'],
    ['Iran', 'middle_east'], ['United Arab Emirates', 'middle_east'],
    ['India', 'asia'], ['Japan', 'asia'], ['Australia', 'oceania'],
    ['South Africa', 'africa'], ['', 'unknown'], ['Unspecified', 'unknown'],
  ]) assert.equal(academicRegion(country), region, country);
});

test('academic regions filter academic rows only; old profiles stay worldwide', () => {
  const member = fresh();
  const eu = {kind: 'predoc', country: 'Netherlands'};
  const ca = {kind: 'phd', country: 'Canada'};
  assert.equal(matchesPreferences(eu, member), true);
  assert.equal(matchesPreferences({...eu, country: ''}, member), true);
  assert.equal(matchesPreferences(eu, {...member, academic_regions: {europe: '2026-10-30T00:00:00Z'}}), true);
  assert.equal(matchesPreferences({...eu, country: 'Canada'},
    {...member, academic_regions: {europe: '2026-10-30T00:00:00Z'}}), false);
  assert.equal(matchesPreferences({...eu, country: ''},
    {...member, academic_regions: {europe: '2026-10-30T00:00:00Z'}}), false);
  assert.equal(matchesPreferences({...eu, country: ''},
    {...member, academic_regions: {unknown: '2026-10-30T00:00:00Z'}}), true);
  assert.equal(matchesPreferences({category: 'data_analyst', scope: 'iran'},
    {...member, academic_regions: {europe: '2026-10-30T00:00:00Z'}}), true);
  assert.equal(matchesPreferences(ca, member), false); // PhD topic not selected
  assert.equal(matchesPreferences(eu, {...member, academic_regions: undefined}), true);
  assert.equal(validPreferences({...member, academic_regions: {fake: '2026-10-30T00:00:00Z'}}), false);
  assert.equal(validPreferences({...member, academic_regions: {europe: 123}}), false);
});

test('region toggles save without editing career markets; legacy market callback returns career screen', async () => {
  const member = fresh();
  const values = new Map([['subscribers_initialized', true], ['subscriber:42', member]]);
  const messages = [];
  const storage = {get: async k => structuredClone(values.get(k)),
    put: async (k,v) => values.set(k, structuredClone(v)),
    delete: async k => values.delete(k),
    list: async ({prefix} = {}) => new Map([...values].filter(([k]) => !prefix || k.startsWith(prefix))),
    transaction: async fn => fn(storage)};
  const bot = {ctx: {storage}, env: {OWNER_IDS: ''}, api: async () => {},
    deliver: async (_key, _method, content) => messages.push(content)};
  const msg = {chat: {id: 42, type: 'private'}, message_id: 12};
  const tap = async (data, key) => {
    await subscriberUpdate(bot, msg, {id: key, data}, key);
    return messages.at(-1);
  };
  await tap('sub:r:europe', 'eu');
  assert.deepEqual(Object.keys(values.get('subscriber:42').academic_regions), ['europe']);
  assert.deepEqual(Object.keys(values.get('subscriber:42').scopes), ['iran']);
  await tap('sub:r:north_america', 'na');
  assert.ok(values.get('subscriber:42').academic_regions.north_america);
  await tap('sub:g:remote', 'remote');
  assert.ok(values.get('subscriber:42').scopes.remote);
  assert.ok(callbacks(messages.at(-1)).includes('sub:t:data_analyst'));
  await tap('sub:p:markets', 'old-menu');
  assert.match(messages.at(-1).text, /Career roles/i);
  await tap('sub:r:all', 'all');
  assert.deepEqual(values.get('subscriber:42').academic_regions, {});
  assert.equal(validPreferences(values.get('subscriber:42')), true);
});
