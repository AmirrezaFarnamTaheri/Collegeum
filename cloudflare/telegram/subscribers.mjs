/** Private preferences. Delivery receipts remain in the encrypted Python journal. */
export const TOPICS = ['predoc', 'phd', 'postdoc', 'research', 'life_sciences_phd',
  'data_scientist', 'data_analyst', 'econ_consulting', 'research_analyst'];
const ACADEMIC = TOPICS.slice(0, 4), CAREERS = TOPICS.slice(5);
const ZONES = ['UTC', 'Asia/Tehran', 'Europe/London', 'America/New_York'];
const LIMITS = [3, 6, 10];
export const PAGE_SIZES = [3, 4, 6, 8];
export const pageSize = value => PAGE_SIZES.includes(value) ? value : 4;
const LOOKBACK_DAYS = [7, 14, 30, 60, 90];
const DEFAULT_LOOKBACK = 14;
const selectedWindow = value => LOOKBACK_DAYS.includes(value) ? value : DEFAULT_LOOKBACK;
const latestSelection = (raw, preferred = DEFAULT_LOOKBACK) => {
  if (raw === 'sub:p:latest') return {days: selectedWindow(preferred), page: 0};
  // Existing Telegram messages contain page-only callbacks; keep them usable.
  const old = /^sub:p:latest:([0-9]{1,3})$/.exec(raw);
  if (old && Number(old[1]) < 10) return {days: selectedWindow(preferred), page: Number(old[1])};
  const selected = /^sub:p:latest:(7|14|30|60|90):([0-9]{1,3})$/.exec(raw);
  if (!selected || Number(selected[2]) >= 500) return null;
  return {days: Number(selected[1]), page: Number(selected[2])};
};
const lookbackLabel = (days, fa) => fa ? ({
  7: '۷ روز اخیر', 14: '۱۴ روز اخیر', 30: '۳۰ روز اخیر',
  60: '۶۰ روز اخیر', 90: '۹۰ روز اخیر',
})[days] : `last ${days} days`;
const lookbackChoices = (days, fa, setting = false) => [[7, 14], [30, 60], [90]].map(row =>
  row.map(value => button(
    `${days === value ? '☑' : '☐'} ${fa ? ({
      7: '۷ روز', 14: '۱۴ روز', 30: '۱ ماه', 60: '۲ ماه', 90: '۳ ماه',
    })[value] : ({
      7: '7 days', 14: '14 days', 30: '1 month', 60: '2 months', 90: '3 months',
    })[value]}`,
    setting ? `sub:w:${value}` : `sub:p:latest:${value}:0`,
  )));
export const matchesPreferences = (row, member) => Boolean(member &&
  (row.category || row.kind) in member.topics &&
  (!row.scope || row.scope in member.scopes));
const LABELS = {
  en: ['Predoc / research assistant', 'PhD positions', 'Postdocs', 'Research staff',
    'Life Sciences PhD · Europe', 'Data science', 'Data analysis / BI',
    'Economics consulting', 'Research / economic analysis'],
  fa: ['پیشادکتری / دستیار پژوهشی', 'فرصت دکتری', 'پسادکتری', 'پژوهشگر حرفه‌ای',
    'دکتری علوم زیستی · اروپا', 'علم داده', 'تحلیل داده / BI', 'مشاوره اقتصادی', 'تحلیل پژوهش و اقتصاد'],
};
const escape = text => String(text).replace(/[&<>"']/g, c =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const button = (text, data) => ({text, callback_data: data});
const safeApplicationUrl = value => {
  if (typeof value !== 'string' || value.length > 1024) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname && !url.username && !url.password
      ? url.href : '';
  } catch { return ''; }
};
// A date-only deadline has no employer-provided closing time. Keep it visible
// through its UTC calendar date; never claim the application is verified open.
const deadlineNotPassed = (value, now) => {
  if (!value) return true;
  if (typeof value !== 'string') return false;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value))
    return value >= new Date(now).toISOString().slice(0, 10);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp >= now;
};
const recentlyDiscovered = (value, days, now) => {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp <= now && timestamp >= now - days * 86400000;
};
const fresh = () => ({topics: {}, scopes: {}, paused: false, language: 'en',
  delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC'});

export function validPreferences(value) {
  if (value === null) return true;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (Object.keys(value).some(k => !Object.keys(fresh()).includes(k))) return false;
  for (const [field, allowed] of [['topics', TOPICS], ['scopes', ['iran', 'remote']]]) {
    if (!value[field] || typeof value[field] !== 'object' || Array.isArray(value[field])) return false;
    if (Object.entries(value[field]).some(([key, at]) => !allowed.includes(key) ||
      typeof at !== 'string' || !Number.isFinite(Date.parse(at)))) return false;
  }
  return typeof value.paused === 'boolean' && ['en', 'fa'].includes(value.language) &&
    ['instant', 'digest'].includes(value.delivery_mode) && LIMITS.includes(value.daily_limit) &&
    typeof value.quiet_hours === 'boolean' && ZONES.includes(value.timezone);
}

export function panel(member, page = 'home', size = 4, windowDays = DEFAULT_LOOKBACK) {
  const m = member || fresh(), fa = m.language === 'fa';
  const tr = (en, persian) => fa ? persian : en;
  const parent = ['academic', 'careers', 'life_sciences', 'markets'].includes(page) ? 'subscriptions' :
    ['display', 'history'].includes(page) ? 'more' : 'home';
  const home = [button(parent === 'subscriptions' ? tr('← Subscriptions', '← اشتراک‌ها') :
    parent === 'more' ? tr('← Settings', '← تنظیمات') : tr('← Home', '← خانه'), `sub:p:${parent}`)];
  const link = (en, persian, page) => button(tr(en, persian), `sub:p:${page}`);
  let text, rows;
  if (page === 'subscriptions') {
    const nAcademic = ACADEMIC.filter(key => key in m.topics).length;
    const nCareers = CAREERS.filter(key => key in m.topics).length;
    const nMarkets = Object.keys(m.scopes).length;
    const nLife = 'life_sciences_phd' in m.topics ? 1 : 0;
    text = tr('🧭 <b>Subscriptions</b>\n\nChoose your roles and markets. Changes save immediately.\n'
      + `🎓 Academic ${nAcademic}/4 · 💼 Careers ${nCareers}/4\n`
      + `🧬 Life Sciences ${nLife}/1 · 🌍 Markets ${nMarkets}/2\n\n`
      + 'Job markets apply to career roles only; academic roles do not need one.',
      '🧭 <b>اشتراک‌ها</b>\n\nموضوع‌ها و محدوده دلخواه را انتخاب کنید. تغییرات فوری ذخیره می‌شوند.\n'
      + `🎓 دانشگاهی ${nAcademic}/4 · 💼 شغلی ${nCareers}/4\n`
      + `🧬 علوم زیستی ${nLife}/1 · 🌍 محدوده‌ها ${nMarkets}/2\n\n`
      + 'محدوده‌های شغلی فقط برای مشاغل هستند؛ فرصت‌های دانشگاهی به محدوده نیاز ندارند.');
    if (nCareers && !nMarkets) text += tr(
      '\n\n⚠️ Select at least one market to see career matches.',
      '\n\n⚠️ برای دیدن مشاغل، دست‌کم یک محدوده را انتخاب کنید.');
    rows = [[link(`🎓 Academic · ${nAcademic}/4`, `🎓 دانشگاهی · ${nAcademic}/4`, 'academic'),
      link(`💼 Careers · ${nCareers}/4`, `💼 مشاغل · ${nCareers}/4`, 'careers')],
      [link(`🧬 Life Sciences · ${nLife}/1`, `🧬 علوم زیستی · ${nLife}/1`, 'life_sciences'),
        link(`🌍 Markets · ${nMarkets}/2`, `🌍 محدوده‌ها · ${nMarkets}/2`, 'markets')],
      [link('🔎 View my matches', '🔎 فرصت‌های من', 'latest'),
        link('🗓 Match history', '🗓 بازه زمانی', 'history')]];
  } else if (['academic', 'careers', 'life_sciences', 'markets'].includes(page)) {
    const options = page === 'academic' ? ACADEMIC : page === 'careers' ? CAREERS :
      page === 'life_sciences' ? ['life_sciences_phd'] : ['iran', 'remote'];
    const field = page === 'markets' ? 'scopes' : 'topics';
    text = page === 'academic' ? tr('<b>Academic roles</b>\n\nChoose roles. Predocs are before a PhD; research staff may need a completed PhD.',
      '<b>فرصت‌های دانشگاهی</b>\n\nموضوع دلخواه را انتخاب کنید. پیشادکتری پیش از دکتری است؛ پژوهشگر حرفه‌ای ممکن است دکتری بخواهد.') :
      page === 'markets' ? tr('<b>Job markets</b>\n\nChoose one or both markets for career alerts. Academic roles are not restricted by these markets.', '<b>محدوده مشاغل</b>\n\nبرای اعلان مشاغل یک یا هر دو محدوده را انتخاب کنید. این محدوده‌ها فرصت‌های دانشگاهی را محدود نمی‌کنند.') :
      page === 'careers' ? tr('<b>Career roles</b>\n\nChoose roles, then a job market.', '<b>مشاغل</b>\n\nموضوع‌ها و سپس محدوده جستجو را انتخاب کنید.') :
      tr('<b>Life Sciences PhD · Europe</b>\n\nToggle alerts for doctoral openings.', '<b>دکتری علوم زیستی · اروپا</b>\n\nاعلان فرصت‌های دکتری را روشن یا خاموش کنید.');
    const count = options.filter(key => key in m[field]).length;
    text += '\n\n' + tr(`Selected: ${count}/${options.length} · ☑ On · ☐ Off · Tap to change`,
      `انتخاب‌شده: ${count}/${options.length} · ☑ فعال · ☐ غیرفعال · برای تغییر لمس کنید`);
    if (page === 'careers' && !Object.keys(m.scopes).length) text += tr(
      '\n\n⚠️ Choose a job market to enable career matches.',
      '\n\n⚠️ برای دیدن مشاغل محدوده جستجو را انتخاب کنید.');
    if (page === 'markets' && !CAREERS.some(key => key in m.topics)) text += tr(
      '\n\nℹ️ Choose at least one Career role. Markets do not filter academic roles.',
      '\n\nℹ️ دست‌کم یک موضوع شغلی انتخاب کنید. محدوده‌ها فرصت‌های دانشگاهی را محدود نمی‌کنند.');
    rows = options.map(key => [button((key in m[field] ? '☑ ' : '☐ ') +
      (key === 'iran' ? tr('Iran', 'ایران') : key === 'remote' ? tr('Worldwide remote', 'دورکاری جهانی') :
        LABELS[m.language][TOPICS.indexOf(key)]), `sub:${field === 'topics' ? 't' : 'g'}:${key}`)]);
    if (['academic', 'careers'].includes(page)) {
      const all = options.every(key => key in m.topics);
      rows.push([button(all ? tr('Clear all', 'پاک‌کردن همه') : tr('Select all', 'انتخاب همه'),
        `sub:b:${page}:${all ? 'off' : 'on'}`)]);
    }
    if (page === 'careers') rows.push([link(
      `🌍 Job markets · ${Object.keys(m.scopes).length}/2 →`,
      `🌍 محدوده مشاغل · ${Object.keys(m.scopes).length}/2 ←`, 'markets')]);
    rows.push([link('🔎 View my matches', '🔎 فرصت‌های من', 'latest'), link('🗓 History', '🗓 بازه زمانی', 'history')]);
  } else if (page === 'delivery') {
    text = tr('<b>Alert delivery</b>', '<b>ارسال اعلان‌ها</b>') + '\n\n' +
      tr('Changes apply at the next scheduled alert run. Individual alerts are sent when new matches are collected.',
        'تغییرات در اجرای بعدی ارسال اعمال می‌شوند. اعلان تکی پس از گردآوری فرصت تازه ارسال می‌شود.');
    rows = [[button(tr('Mode: ', 'روش: ') + (m.delivery_mode === 'digest' ? tr('Daily digest', 'خلاصه روزانه') : tr('Individual', 'تکی')), 'sub:d:mode')],
      [button(tr('Daily maximum: ', 'حد روزانه: ') + m.daily_limit, 'sub:d:limit')],
      [button(tr('Quiet hours: ', 'ساعات آرام: ') + (m.quiet_hours ? '22:00–08:00' : tr('Off', 'خاموش')), 'sub:d:quiet')],
      [button(tr('Time zone: ', 'منطقه زمانی: ') + m.timezone, 'sub:d:zone')]];
    rows.push([button(m.paused ? tr('Resume alerts', 'ازسرگیری اعلان') : tr('Pause alerts', 'توقف اعلان'),
      m.paused ? 'sub:a:resume' : 'sub:a:pause')]);
  } else if (page === 'display') {
    text = tr('<b>Display settings</b>\n\nBrowse results: choose positions per page. This does not change your daily alert limit.',
      '<b>تنظیمات نمایش</b>\n\nتعداد فرصت در هر صفحه. این تنظیم حد اعلان روزانه را تغییر نمی‌دهد.');
    rows = [PAGE_SIZES.slice(0, 2), PAGE_SIZES.slice(2)].map(options => options.map(n =>
      button(`${n === pageSize(size) ? '☑' : '☐'} ${n}`, `sub:n:${n}`)));
    rows.push([link('Match history: ' + lookbackLabel(selectedWindow(windowDays), false),
      'بازه مرور فرصت‌ها: ' + lookbackLabel(selectedWindow(windowDays), true), 'history')]);
  } else if (page === 'history') {
    const days = selectedWindow(windowDays);
    text = tr('<b>Match history</b>\n\nChoose how far back My matches searches. This changes browsing only, not new-job alerts or previous deliveries.',
      '<b>بازه زمانی فرصت‌ها</b>\n\nبازه جستجوی «فرصت‌های من» را انتخاب کنید. این انتخاب اعلان‌های جدید و سابقه ارسال را تغییر نمی‌دهد.');
    text += '\n\n' + tr('Saved default: ', 'بازه پیش‌فرض ذخیره‌شده: ') +
      lookbackLabel(days, fa) + '\n' +
      tr('☑ Selected · ☐ Not selected', '☑ انتخاب‌شده · ☐ انتخاب نشده');
    rows = [...lookbackChoices(days, fa, true),
      [link('🔎 View my matches →', '🔎 مشاهده فرصت‌های من ←', 'latest')]];
  } else if (page === 'stop') {
    text = tr('<b>Unsubscribe?</b>\n\nRemove your active preferences and stop future alerts. Previously encrypted backups may remain.',
      '<b>لغو عضویت؟</b>\n\nتنظیمات فعال حذف و اعلان‌ها متوقف می‌شوند. نسخه‌های پشتیبان رمزگذاری‌شده قبلی ممکن است باقی بمانند.');
    rows = [[button(tr('Unsubscribe', 'لغو عضویت'), 'sub:stop:yes')]];
  } else if (page === 'privacy') {
    text = tr('<b>Privacy</b>\n\nYour chat ID and preferences are stored privately in Cloudflare. Scheduled alerts keep encrypted preferences and delivery records. /delete removes the active subscription; older backups may remain.',
      '<b>حریم خصوصی</b>\n\nشناسه گفت‌وگو و تنظیمات به‌صورت خصوصی در کلادفلر ذخیره می‌شوند. ارسال زمان‌بندی‌شده، تنظیمات و سوابق رمزگذاری‌شده را نگه می‌دارد. /delete اشتراک فعال را حذف می‌کند؛ پشتیبان‌های قدیمی ممکن است باقی بمانند.');
    rows = [];
  } else if (page === 'help') {
    text = tr('❔ <b>How Collegeum works</b>\n\n'
      + '1. Subscriptions → select Academic, Careers or Life Sciences roles. Careers also require a market.\n'
      + '2. My matches → browse saved roles from the last 7, 14, 30, 60 or 90 days.\n'
      + '3. Settings → Match history saves your default range. Display controls page size.\n'
      + '4. Alert delivery → choose notification mode, quota, time zone and quiet hours.\n\n'
      + 'New alerts are only for jobs discovered after you subscribe; changing history never resends old posts. '
      + 'Collection is scheduled, so missing listings can mean an outdated snapshot. '
      + 'Always confirm eligibility and opening status on the original employer site.',
      '❔ <b>راهنمای کالجیوم</b>\n\n'
      + '۱. از اشتراک‌ها موضوع‌های دانشگاهی، شغلی یا علوم زیستی را انتخاب کنید. مشاغل به محدوده نیاز دارند.\n'
      + '۲. فرصت‌های من: بازه‌های ۷، ۱۴، ۳۰، ۶۰ و ۹۰ روز را مرور کنید.\n'
      + '۳. تنظیمات: بازه زمانی پیش‌فرض و تعداد نتایج در صفحه را تعیین کنید.\n'
      + '۴. ارسال اعلان: روش، سقف روزانه، منطقه زمانی و ساعات آرام را تغییر دهید.\n\n'
      + 'اعلان فقط برای فرصت‌های تازه پس از عضویت است؛ تغییر بازه موجب ارسال دوباره نمی‌شود. '
      + 'گردآوری زمان‌بندی‌شده است و ممکن است فهرست موقتاً قدیمی باشد. '
      + 'وضعیت پذیرش و شرایط را در وب‌سایت کارفرما بررسی کنید.');
    rows = [[link('🧭 Subscriptions', '🧭 اشتراک‌ها', 'subscriptions'),
      link('🗓 History settings', '🗓 بازه زمانی', 'history')]];
  } else if (page === 'more') {
    text = tr('⚙️ <b>Settings</b>\n\n'
      + 'Browse preferences affect only the way results are shown. '
      + 'Alert delivery controls new notifications.',
      '⚙️ <b>تنظیمات</b>\n\n'
      + 'تنظیمات مرور فقط نمایش نتایج را تغییر می‌دهد. '
      + 'ارسال اعلان، پیام‌های فرصت‌های تازه را کنترل می‌کند.');
    rows = [[link('🗓 History: ' + lookbackLabel(selectedWindow(windowDays), false),
      '🗓 بازه: ' + lookbackLabel(selectedWindow(windowDays), true), 'history'),
      link('📄 Page size: ' + pageSize(size), '📄 تعداد در صفحه: ' + pageSize(size), 'display')],
      [link('🔔 Alert delivery', '🔔 ارسال اعلان', 'delivery'),
        link('🌍 Job markets', '🌍 محدوده مشاغل', 'markets')],
      [link('🌐 Source status', '🌐 وضعیت منابع', 'sources'),
        link('❔ Help', '❔ راهنما', 'help')],
      [button(fa ? '🌐 English' : '🌐 فارسی', `sub:l:${fa ? 'en' : 'fa'}`),
        link('🔒 Privacy', '🔒 حریم خصوصی', 'privacy')],
      [link('🗑 Unsubscribe', '🗑 لغو عضویت', 'stop')]];
  } else {
    const nAcademic = ACADEMIC.filter(key => key in m.topics).length;
    const nCareers = CAREERS.filter(key => key in m.topics).length;
    const nLife = 'life_sciences_phd' in m.topics ? 1 : 0;
    const markets = [m.scopes.iran ? tr('Iran', 'ایران') : '',
      m.scopes.remote ? tr('Worldwide remote', 'دورکاری جهانی') : ''].filter(Boolean);
    const ready = nAcademic > 0 || nLife > 0 || (nCareers > 0 && markets.length);
    const status = !ready ? tr('Not configured', 'تنظیم نشده') :
      m.paused ? tr('Paused', 'متوقف') : tr('On', 'فعال');
    text = tr('🎯 <b>Collegeum · Career radar</b>', '🎯 <b>کالجیوم · رادار فرصت‌ها</b>') +
      '\n\n' + tr(`🎓 Academic: ${nAcademic}/4 · 💼 Careers: ${nCareers}/4\n` +
        `🧬 Life Sciences: ${nLife ? 'On' : 'Off'}\n`,
        `🎓 دانشگاهی: ${nAcademic}/4 · 💼 مشاغل: ${nCareers}/4\n` +
        `🧬 علوم زیستی: ${nLife ? 'فعال' : 'غیرفعال'}\n`) +
      tr('🌍 Markets: ', '🌍 محدوده‌ها: ') +
      escape(markets.join(' + ') || tr('Not selected', 'انتخاب نشده')) + '\n' +
      tr('🔔 Alerts: ', '🔔 اعلان‌ها: ') + status + '\n' +
      tr('🗓 Browse range: ', '🗓 بازه مرور: ') + lookbackLabel(selectedWindow(windowDays), fa);
    text += '\n\n' + (!ready ? tr(
      'Choose roles under Subscriptions. Existing matches can then be browsed.',
      'از اشتراک‌ها موضوع دلخواه را انتخاب کنید، سپس فرصت‌های قبلی را مرور کنید.') :
      m.paused ? tr('Your selections are saved; alerts are paused.',
        'تنظیمات ذخیره شده‌اند اما اعلان‌ها متوقف هستند.') :
        tr('Browse existing positions below. New alerts follow the collection schedule.',
          'فرصت‌های موجود را مرور کنید. اعلان‌های جدید طبق برنامه گردآوری ارسال می‌شوند.'));
    if (nCareers && !markets.length) text += tr(
      '\n\n⚠️ Career roles need at least one job market.',
      '\n\n⚠️ برای مشاغل دست‌کم یک محدوده لازم است.');
    rows = [[link('🔎 View my matches', '🔎 فرصت‌های من', 'latest')],
      [link('🧭 Subscriptions', '🧭 اشتراک‌ها', 'subscriptions'),
        link('🔔 Alert delivery', '🔔 ارسال اعلان', 'delivery')],
      [link('⚙️ Settings', '⚙️ تنظیمات', 'more'),
        link('❔ Help', '❔ راهنما', 'help')]];
    if (nCareers && !markets.length)
      rows.splice(2, 0, [link('🌍 Choose a job market', '🌍 انتخاب محدوده مشاغل', 'markets')]);
    return {text, reply_markup: {inline_keyboard: rows}};
  }
  rows.push(home);
  return {text, reply_markup: {inline_keyboard: rows}};
}

const PAGES = new Set(['home', 'subscriptions', 'display', 'history', 'academic', 'careers', 'life_sciences', 'markets', 'delivery',
  'more', 'help', 'privacy', 'stop', 'latest', 'sources']);
const COMMAND_PAGES = {start: 'home', settings: 'more', subscribe: 'subscriptions', status: 'home',
  academic: 'academic', careers: 'careers', markets: 'markets', lifesciences: 'life_sciences',
  delivery: 'delivery', guide: 'help', privacy: 'privacy', stop: 'stop', delete: 'stop',
  latest: 'latest', matches: 'latest', subscriptions: 'subscriptions',
  history: 'history', display: 'display', notifications: 'delivery',
  sources: 'sources', help: 'help', more: 'more'};
export const subscriberCommand = command => (Object.hasOwn(COMMAND_PAGES, command) &&
  !['help', 'more'].includes(command)) || ['pause', 'resume'].includes(command);

export async function subscriberUpdate(bot, message, callback, key) {
  if (!await bot.ctx.storage.get('subscribers_initialized')) {
    await bot.deliver(key, 'sendMessage', {chat_id: message.chat.id,
      text: 'Alert settings are being connected. Please try again later.'});
    return;
  }
  const command = String(message.text || '').trim().split(/\s+/)[0].replace(/^\//, '').split('@')[0].toLowerCase();
  const raw = callback?.data || (['pause', 'resume'].includes(command) ? `sub:a:${command}` : `sub:p:${COMMAND_PAGES[command] || 'home'}`);
  const id = String(message.chat.id);
  const preferredWindow = selectedWindow(await bot.ctx.storage.get(`match_window:${id}`));
  const selection = latestSelection(raw, preferredWindow);
  const page = await bot.ctx.storage.transaction(async tx => {
    const claim = await tx.get(key);
    if (claim?.subscriber_applied) return claim.subscriber_page;
    const old = await tx.get(`subscriber:${id}`), m = old || fresh();
    let target = 'home', changed = false;
    const parts = raw.split(':');
    if (selection) target = 'latest';
    else if (parts.length === 3 && parts[1] === 'p' && PAGES.has(parts[2]) &&
      parts[2] !== 'latest') target = parts[2];
    else if (parts.length === 3 && (parts[1] === 't' && TOPICS.includes(parts[2]) ||
      parts[1] === 'g' && ['iran', 'remote'].includes(parts[2]))) {
      const field = parts[1] === 't' ? 'topics' : 'scopes', option = parts[2];
      if (option in m[field]) delete m[field][option]; else m[field][option] = new Date().toISOString();
      target = field === 'scopes' ? 'markets' : option === 'life_sciences_phd' ? 'life_sciences' : ACADEMIC.includes(option) ? 'academic' : 'careers';
      changed = true;
    } else if (parts.length === 4 && parts[1] === 'b' && ['academic', 'careers'].includes(parts[2]) && ['on', 'off'].includes(parts[3])) {
      for (const topic of parts[2] === 'academic' ? ACADEMIC : CAREERS) {
        if (parts[3] === 'on') m.topics[topic] ||= new Date().toISOString(); else delete m.topics[topic];
      }
      target = parts[2]; changed = true;
    } else if (parts.length === 3 && parts[1] === 'l' && ['en', 'fa'].includes(parts[2])) {
      m.language = parts[2]; changed = true; target = 'more';
    } else if (parts[1] === 'a' && ['pause', 'resume'].includes(parts[2]) && old) {
      m.paused = parts[2] === 'pause'; changed = true; target = 'delivery';
    } else if (parts[1] === 'd' && old) {
      const fields = {mode: ['delivery_mode', ['instant', 'digest']], limit: ['daily_limit', LIMITS],
        zone: ['timezone', ZONES], quiet: ['quiet_hours', [false, true]]};
      if (!fields[parts[2]]) return 'home';
      const [field, options] = fields[parts[2]];
      m[field] = options[(options.indexOf(m[field]) + 1) % options.length];
      target = 'delivery'; changed = true;
    } else if (raw === 'sub:stop:yes') {
      await tx.put(`subscriber:${id}`, null);
      await tx.delete(`page_size:${id}`);
      await tx.delete(`match_window:${id}`);
    } else if (parts.length === 3 && parts[1] === 'w' &&
      LOOKBACK_DAYS.some(n => String(n) === parts[2])) {
      await tx.put(`match_window:${id}`, Number(parts[2]));
      target = 'history';
    } else if (parts.length === 3 && parts[1] === 'n' && PAGE_SIZES.some(n => String(n) === parts[2])) {
      await tx.put(`page_size:${id}`, Number(parts[2]));
      target = 'display';
    } else return 'home';
    if (changed) {
      const members = await tx.list({prefix: 'subscriber:'});
      if (!members.has(`subscriber:${id}`) && members.size >= 1000) return 'full';
      await tx.put(`subscriber:${id}`, m);
    }
    await tx.put(key, {...claim, subscriber_applied: true, subscriber_page: target});
    return target;
  });
  const member = await bot.ctx.storage.get(`subscriber:${id}`);
  const size = pageSize(await bot.ctx.storage.get(`page_size:${id}`));
  const windowDays = selectedWindow(await bot.ctx.storage.get(`match_window:${id}`));
  let content = panel(member, page, size, windowDays);
  if (page === 'full') content.text = 'Subscriptions are full. Please try again later.';
  if (page === 'sources') {
    const fa = member?.language === 'fa';
    content = {
      text: (await bot.ctx.storage.get('source_status'))?.[fa ? 'fa' : 'en'] ||
        (fa ? 'هنوز گزارش بررسی منابع در دسترس نیست.' :
          'No source-check report is available yet.'),
      reply_markup: {inline_keyboard: [[
        button(fa ? '← تنظیمات' : '← Settings', 'sub:p:more'),
        button(fa ? '🔎 فرصت‌های من' : '🔎 My matches', 'sub:p:latest'),
      ]]},
    };
  }
  if (page === 'latest') {
    const owner = (bot.env?.OWNER_IDS || '').split(',').map(s => s.trim()).includes(id);
    const {rows, marks} = await bot.dataset(owner);
    const now = Date.now(), days = selection.days;
    // Python's public-record export historically omitted published_at.
    // The immutable first_seen_at is the consistent discovery timestamp for
    // academic and career history windows; last_seen_at is not a new listing.
    const academic = rows.filter(r => matchesPreferences(r, member) &&
      !r.closed_at && !r.expired_at &&
      !['invalid', 'applied'].includes(marks?.get(r.url_hash)) &&
      recentlyDiscovered(r.first_seen_at || r.published_at, days, now) &&
      deadlineNotPassed(r.deadline, now) && safeApplicationUrl(r.apply_url));
    const careerInventory = await bot.ctx.storage.get('career_listings') || [];
    const careers = careerInventory.filter(r => matchesPreferences(r, member) && r.availability !== 'closed' &&
        deadlineNotPassed(r.deadline, now) &&
        recentlyDiscovered(r.first_seen_at, days, now) && safeApplicationUrl(r.url))
      .map(r => ({...r, apply_url: r.url, institution: r.employer,
        published_at: r.first_seen_at}));
    const matches = [...academic, ...careers].sort((a, b) =>
      Date.parse(b.first_seen_at || b.published_at) - Date.parse(a.first_seen_at || a.published_at));
    const fa = member?.language === 'fa';
    const totalPages = Math.max(1, Math.ceil(matches.length / size));
    const current = Math.min(totalPages - 1, selection.page);
    const snapshot = await bot.ctx.storage.get('snapshot_at');
    const snapshotAt = Date.parse(snapshot);
    const snapshotWarning = !Number.isFinite(snapshotAt)
      ? (fa ? '⚠️ هنوز هیچ نسخه‌ای از فهرست فرصت‌ها همگام‌سازی نشده است.' :
        '⚠️ Listing snapshot has not been synced yet. Run telegram-sync to connect the inventory.')
      : now - snapshotAt > 8 * 3600000
        ? (fa ? '⚠️ فهرست فرصت‌ها بیش از ۸ ساعت است به‌روزرسانی نشده است.' :
          '⚠️ Listing snapshot is over 8 hours old; results may be incomplete.')
        : '';
    const entries = matches.slice(current * size, current * size + size).map((r, index) =>
      `${current * size + index + 1}. <a href="${escape(safeApplicationUrl(r.apply_url))}">${escape(String(r.title || 'Opportunity').slice(0, 110))}</a>\n` +
      escape(String(r.institution || 'Employer unknown').slice(0, 90)) +
      (r.country ? ` · ${escape(String(r.country).slice(0, 50))}` : '') +
      (r.deadline ? `\n${fa ? 'مهلت' : 'Deadline'}: ${escape(String(r.deadline).slice(0, 10))}` : '') +
      (r.category && r.availability !== 'active'
        ? (fa ? '\nℹ️ وضعیت پذیرش تأیید نشده است.' : '\nℹ️ Availability unverified.') : '') +
      (r.category === 'life_sciences_phd'
        ? (fa ? '\nℹ️ تأمین مالی تأیید نشده است.' : '\nℹ️ Funding unverified.') : ''));
    const needsCareerMarket = member && CAREERS.some(topic => topic in member.topics) &&
      !Object.keys(member.scopes || {}).length;
    const empty = !member || !Object.keys(member.topics || {}).length
      ? (fa ? 'ابتدا موضوع دلخواه را در اشتراک‌ها انتخاب کنید.' :
        'Choose an academic or career role in Subscriptions first.')
      : needsCareerMarket && !academic.length
        ? (fa ? 'برای دیدن مشاغل باید یک محدوده شغلی انتخاب کنید: ایران یا دورکاری جهانی.' :
          'Choose a job market (Iran or worldwide remote) to see career matches.')
        : (fa ? 'در این بازه فرصت منطبق پیدا نشد. بازه ۳ ماهه یا موضوع‌های دیگر را امتحان کنید.' :
          'No matches in this window. Try 3 months or broaden your selected roles.');
    const header = (fa ? '<b>فرصت‌های من</b>' : '<b>My matches</b>') + '\n\n' +
      (fa ? 'موضوع‌ها و محدوده‌های انتخاب‌شده' : 'Your selected roles and career markets') +
      ' · ' + lookbackLabel(days, fa) + '\n' +
      (fa ? `${matches.length} مورد منطبق` : `${matches.length} matches`) + '\n' +
      (fa ? `📦 فهرست: ${rows.length} دانشگاهی · ${careerInventory.length} شغلی`
        : `📦 Cached inventory: ${rows.length} academic · ${careerInventory.length} career records`);
    const footer = fa ? 'ℹ️ مشاهده آگهی به معنی باز بودن یا تأمین مالی تأییدشده نیست.' :
      'ℹ️ A discovered listing is not a verified open or funded vacancy.';
    content = {text: [header, snapshotWarning, entries.join('\n\n') || empty, footer]
      .filter(Boolean).join('\n\n'),
      reply_markup: {inline_keyboard: [
        ...lookbackChoices(days, fa),
        ...(totalPages > 1 ? [[...(current ? [button('‹', `sub:p:latest:${days}:${current - 1}`)] : []),
          button(`${current + 1}/${totalPages}`, `sub:p:latest:${days}:${current}`),
          ...(current + 1 < totalPages ? [button('›', `sub:p:latest:${days}:${current + 1}`)] : [])]] : []),
        [button(fa ? 'تنظیمات بازه زمانی' : 'Save preferred range', 'sub:p:history'),
          button(fa ? 'تنظیمات نمایش' : `Page size: ${size}`, 'sub:p:display')],
        [button(fa ? 'اشتراک‌ها' : 'Edit subscriptions', 'sub:p:subscriptions'),
          button(fa ? 'خانه' : 'Home', 'sub:p:home')]]}};
  }
  if (['home', 'more', 'latest'].includes(page) &&
      (bot.env?.OWNER_IDS || '').split(',').map(s => s.trim()).includes(id))
    content.reply_markup.inline_keyboard.push([{text:
      member?.language === 'fa' ? '📌 ذخیره‌شده و درخواست‌ها' : '📌 Saved & applications',
      callback_data: 'view|tracking|0'}]);
  if (callback) {
    try { await bot.api('answerCallbackQuery', {callback_query_id: callback.id}); } catch { /* expired tap */ }
  }
  await bot.deliver(key, callback ? 'editMessageText' : 'sendMessage', {
    chat_id: message.chat.id, ...(callback ? {message_id: message.message_id} : {}),
    ...content, parse_mode: 'HTML', link_preview_options: {is_disabled: true},
  });
}
