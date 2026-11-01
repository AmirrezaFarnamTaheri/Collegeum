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
  assert.match(screen.text, /Career.*Job markets/i);
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

test('settings have direct matching and delivery controls, without conflating page size and alert limits', () => {
  const settings = panel(member, 'more', 4, 90);
  for (const target of ['sub:p:history', 'sub:p:display', 'sub:p:delivery',
    'sub:p:privacy', 'sub:p:sources']) {
    assert.ok(callbacks(settings).includes(target), target);
  }
  assert.match(settings.text, /brows|alerts?/i);
  const history = panel(member, 'history', 4, 90);
  assert.match(history.text, /90|3 months/);
  assert.ok(callbacks(history).includes('sub:w:90'));
  assert.ok(callbacks(history).includes('sub:p:latest'));
  const display = panel(member, 'display', 6, 90);
  assert.ok(callbacks(display).includes('sub:p:history'));
  assert.match(display.text, /brows/i);
});

test('bilingual menus keep source and account controls reachable with explicit back path', () => {
  for (const language of ['en', 'fa']) {
    const selection = {...member, language};
    for (const page of ['home','subscriptions','academic','careers','life_sciences',
      'academic_regions','markets','delivery','display','history','more','help','privacy','stop']) {
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
