/** Telegram-native visual hierarchy and mobile keyboard regression suite. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {panel} from './subscribers.mjs';

const profile = language => ({
  topics: {predoc: '2026-10-01T00:00:00Z', phd: '2026-10-01T00:00:00Z',
    data_analyst: '2026-10-01T00:00:00Z'},
  scopes: {remote: '2026-10-01T00:00:00Z'},
  academic_regions: {europe: '2026-10-15T00:00:00Z'},
  paused: false, language, delivery_mode: 'instant', daily_limit: 6,
  quiet_hours: false, timezone: 'UTC',
});
const actions = content => content.reply_markup.inline_keyboard.flat()
  .map(button => button.callback_data);
const rowWith = (content, prefix) => content.reply_markup.inline_keyboard
  .filter(row => row.some(button => button.callback_data.startsWith(prefix)));

test('subscriber home has a scannable hero, search and alerts sections with matches first', () => {
  const home = panel(profile('en'), 'home', 12, 90);
  assert.match(home.text, /^🎯 <b>Collegeum<\/b>/);
  assert.match(home.text, /<b>Your search<\/b>/i);
  assert.match(home.text, /<b>Alert status<\/b>/i);
  assert.match(home.text, /Europe/);
  assert.match(home.text, /90 days/);
  assert.equal(home.reply_markup.inline_keyboard[0][0].callback_data, 'sub:p:latest');
  assert.ok(actions(home).includes('sub:p:subscriptions'));
  assert.ok(actions(home).includes('sub:p:more'));
});

test('subscriptions use clear grouped status and a single browse action', () => {
  const view = panel(profile('en'), 'subscriptions');
  assert.match(view.text, /^🧭 <b>Edit subscriptions<\/b>/);
  assert.match(view.text, /<b>🎓 Academic<\/b>/);
  assert.match(view.text, /<b>💼 Careers<\/b>/);
  assert.match(view.text, /<b>🧬 Life Sciences<\/b>/);
  assert.match(view.text, /Iran|remote/i);
  assert.equal(actions(view).filter(data => data === 'sub:p:latest').length, 1);
  assert.ok(!actions(view).includes('sub:p:markets'));
});

test('academic and career choices use short two-column role grids on narrow phones', () => {
  for (const language of ['en', 'fa']) {
    for (const page of ['academic', 'careers']) {
      const view = panel(profile(language), page);
      const roleRows = rowWith(view, 'sub:t:');
      assert.equal(roleRows.length, 2, page + ' should have two role rows');
      assert.deepEqual(roleRows.map(row => row.length), [2, 2]);
      assert.ok(roleRows.flat().every(button => [...button.text].length <= 29),
        page + ' role buttons must be compact');
      assert.match(view.text, language === 'fa' ? /مرحله ۱/ : /Step 1/i);
      assert.match(view.text, language === 'fa' ? /مرحله ۲/ : /Step 2/i);
      assert.ok(actions(view).includes('sub:p:latest'));
      assert.ok(actions(view).includes('sub:p:subscriptions'));
    }
  }
});

test('regional and alert settings show saved state without long instruction blocks', () => {
  for (const language of ['en', 'fa']) {
    const regions = panel(profile(language), 'academic_regions');
    assert.match(regions.text, language === 'fa' ? /مناطق دانشگاهی/ : /Academic regions/);
    assert.match(regions.text, /Europe|اروپا/);
    assert.ok(regions.text.length < 700, 'region selector should be concise');
    assert.ok(actions(regions).includes('sub:r:all'));

    const settings = panel(profile(language), 'more', 12, 90);
    assert.match(settings.text, language === 'fa' ? /مرور/ : /<b>Browsing<\/b>/);
    assert.match(settings.text, language === 'fa' ? /اعلان/ : /<b>Notifications<\/b>/);
    assert.ok(settings.text.length < 700);
    for (const target of ['sub:p:history','sub:p:display','sub:p:delivery']) {
      assert.ok(actions(settings).includes(target));
    }
    const delivery = panel(profile(language), 'delivery');
    assert.match(delivery.text, language === 'fa' ? /وضعیت/ : /Status/i);
    assert.ok(actions(delivery).includes('sub:d:mode'));
    assert.ok(actions(delivery).includes('sub:a:pause'));
  }
});

test('all Telegram menus maintain short callbacks, readable rows and valid HTML', () => {
  for (const language of ['en', 'fa']) {
    for (const page of ['home','subscriptions','academic','academic_regions','careers',
      'life_sciences','delivery','more','history','display','help','stop']) {
      const content = panel(profile(language), page, 12, 90);
      assert.ok(content.text.length <= 4096, page);
      assert.equal((content.text.match(/<b>/g) || []).length,
        (content.text.match(/<\/b>/g) || []).length, page);
      assert.ok(content.reply_markup.inline_keyboard.every(row => row.length <= 2), page);
      assert.ok(content.reply_markup.inline_keyboard.flat().every(button =>
        Buffer.byteLength(button.callback_data) <= 64), page);
    }
  }
});

test('unconfigured subscribers see a truthful alert state and a working setup path', () => {
  const empty = {
    topics: {}, scopes: {}, paused: false, language: 'en',
    delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC',
  };
  const home = panel(empty, 'home');
  const settings = panel(empty, 'more');
  const delivery = panel(empty, 'delivery');
  for (const screen of [home, settings, delivery])
    assert.match(screen.text, /Not configured/);
  assert.doesNotMatch(settings.text, /🔔 Active/);
  assert.ok(actions(delivery).includes('sub:p:subscriptions'));
  const neverEnrolled = panel(null, 'delivery');
  assert.ok(actions(neverEnrolled).includes('sub:p:subscriptions'));
  assert.ok(!actions(neverEnrolled).includes('sub:d:mode'),
    'initial alert settings must not expose inert toggles');
});
