/** Telegram-first IA: predictable hierarchy without changing subscriber semantics. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {panel, subscriberCommand} from './subscribers.mjs';

const member = {
  topics: {predoc: '2026-10-01T00:00:00Z', phd: '2026-10-01T00:00:00Z',
    data_analyst: '2026-10-01T00:00:00Z'},
  scopes: {iran: '2026-10-01T00:00:00Z', remote: '2026-10-01T00:00:00Z'},
  paused: false, language: 'en', delivery_mode: 'instant',
  daily_limit: 6, quiet_hours: false, timezone: 'UTC',
};
const buttons = result => result.reply_markup.inline_keyboard.flat();
const callbacks = result => buttons(result).map(button => button.callback_data);

test('home is a useful summary and offers clear primary paths', () => {
  const home = panel(member, 'home', 4, 90);
  assert.match(home.text, /Academic.*2\/4/i);
  assert.match(home.text, /Career.*1\/4/i);
  assert.match(home.text, /Iran.*remote/i);
  assert.match(home.text, /90 days|3 months/i);
  for (const route of ['sub:p:latest', 'sub:p:subscriptions', 'sub:p:delivery',
    'sub:p:more']) assert.ok(callbacks(home).includes(route), route);
  assert.ok(home.reply_markup.inline_keyboard.length <= 6);
});

test('subscriptions clarify career-market eligibility and link to history and results', () => {
  const screen = panel(member, 'subscriptions');
  assert.match(screen.text, /2\/4/);
  assert.match(screen.text, /1\/4/);
  assert.match(screen.text, /Careers[\s\S]*Job markets/i);
  assert.ok(!callbacks(screen).includes('sub:p:markets'));
  for (const route of ['sub:p:academic', 'sub:p:careers',
    'sub:p:life_sciences', 'sub:p:latest', 'sub:p:history'])
    assert.ok(callbacks(screen).includes(route), route);
});

test('selection screens show progress, preserve bulk actions and offer direct results and history', () => {
  for (const page of ['academic', 'careers', 'academic_regions', 'life_sciences']) {
    const screen = panel(member, page, 4, 90);
    assert.match(screen.text, /selected|current|on/i, page);
    for (const route of ['sub:p:latest']) {
      assert.ok(callbacks(screen).includes(route), page + ': ' + route);
    }
    assert.ok(buttons(screen).every(b => Buffer.byteLength(b.callback_data) <= 64));
    assert.ok(screen.reply_markup.inline_keyboard.every(row => row.length <= 2));
  }
  assert.ok(callbacks(panel(member, 'academic')).includes('sub:b:academic:on'));
  assert.ok(callbacks(panel(member, 'academic')).includes('sub:p:academic_regions'));
  assert.ok(callbacks(panel(member, 'careers')).includes('sub:g:iran'));
  assert.ok(callbacks(panel(member, 'careers')).includes('sub:g:remote'));
  assert.ok(callbacks(panel(member, 'academic_regions')).includes('sub:p:academic'));
});

test('settings is a compact four-destination hub with secondary controls grouped behind panels', () => {
  const settings = panel(member, 'more', 4, 90);
  assert.deepEqual(settings.reply_markup.inline_keyboard.slice(0, 2).map(row =>
    row.map(b => b.callback_data)), [
    ['sub:p:subscriptions', 'sub:p:browse'],
    ['sub:p:delivery', 'sub:p:account'],
  ]);
  assert.ok(settings.text.length < 350);
  assert.match(settings.text, /90 days|3 months/);
  assert.match(settings.text, /Active|6 per day/i);
  for (const leaf of ['sub:p:history', 'sub:p:display', 'sub:p:privacy',
    'sub:p:sources', 'sub:p:help', 'sub:p:stop']) {
    assert.ok(!callbacks(settings).includes(leaf), leaf + ' belongs in its section');
  }
  assert.ok(callbacks(settings).includes('sub:p:home'));

  const browse = panel(member, 'browse', 6, 90);
  assert.match(browse.text, /brows/i);
  for (const route of ['sub:p:history', 'sub:p:display', 'sub:p:latest', 'sub:p:more']) {
    assert.ok(callbacks(browse).includes(route), route);
  }
  assert.ok(!callbacks(browse).includes('sub:p:stop'));
  const history = panel(member, 'history', 6, 90);
  assert.ok(callbacks(history).includes('sub:w:90'));
  assert.ok(callbacks(history).includes('sub:p:browse'));
  const display = panel(member, 'display', 6, 90);
  assert.ok(callbacks(display).includes('sub:p:history'));
  assert.ok(callbacks(display).includes('sub:p:browse'));

  const account = panel(member, 'account');
  for (const route of ['sub:l:fa', 'sub:p:sources', 'sub:p:help', 'sub:p:privacy',
    'sub:p:stop', 'sub:p:more']) {
    assert.ok(callbacks(account).includes(route), route);
  }
  assert.ok(!callbacks(account).includes('sub:p:history'));
  const rows = account.reply_markup.inline_keyboard;
  const unsubscribeRow = rows.find(row => row.some(b => b.callback_data === 'sub:p:stop'));
  assert.equal(unsubscribeRow.length, 1, 'destructive action stands alone');
  assert.equal(callbacks(panel(member, 'stop')).includes('sub:p:account'), true);
  assert.equal(callbacks(panel(member, 'privacy')).includes('sub:p:account'), true);
});

test('nested Settings back labels identify their actual destinations', () => {
  const expected = [
    ['history', 'sub:p:browse', /Browsing/],
    ['display', 'sub:p:browse', /Browsing/],
    ['privacy', 'sub:p:account', /Account/],
    ['stop', 'sub:p:account', /Account/],
    ['help', 'sub:p:account', /Account/],
    ['browse', 'sub:p:more', /Settings/],
    ['account', 'sub:p:more', /Settings/],
  ];
  for (const [page, destination, label] of expected) {
    const screen = panel(member, page, 12, 60);
    const lastRow = screen.reply_markup.inline_keyboard.at(-1);
    assert.equal(lastRow.length, 1, page);
    assert.equal(lastRow[0].callback_data, destination, page);
    assert.match(lastRow[0].text, label, page);
  }
  for (const [page, destination, label] of [
    ['history', 'sub:p:browse', /مرور/],
    ['privacy', 'sub:p:account', /حساب/],
    ['browse', 'sub:p:more', /تنظیمات/],
  ]) {
    const screen = panel({...member, language: 'fa'}, page, 12, 60);
    const last = screen.reply_markup.inline_keyboard.at(-1)[0];
    assert.equal(last.callback_data, destination);
    assert.match(last.text, label);
  }
});

test('bilingual menus keep source and account controls reachable with explicit back path', () => {
  for (const language of ['en', 'fa']) {
    const selection = {...member, language};
    for (const page of ['home','subscriptions','academic','careers','life_sciences',
      'academic_regions','markets','delivery','display','history','browse','more','account','help','privacy','stop']) {
      const screen = panel(selection, page, 4, 14);
      assert.ok(screen.text.length < 4000, page);
      assert.ok(screen.reply_markup.inline_keyboard.every(row => row.length <= 2), page);
      assert.ok(buttons(screen).every(b => Buffer.byteLength(b.callback_data) <= 64), page);
      if (page !== 'home') assert.ok(callbacks(screen).some(data => data.startsWith('sub:p:')), page);
      if (language === 'fa') assert.match(screen.text, /[\u0600-\u06ff]/);
    }
  }
});

test('direct Telegram commands keep the redesigned screens reachable', () => {
  for (const command of ['matches', 'subscriptions', 'history', 'display',
    'notifications', 'settings', 'latest'])
    assert.equal(subscriberCommand(command), true, command);
});
