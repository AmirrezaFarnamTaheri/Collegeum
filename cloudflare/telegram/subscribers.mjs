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
  const home = [button(tr('← Back', '← بازگشت'), `sub:p:${parent}`)];
  const link = (en, persian, page) => button(tr(en, persian), `sub:p:${page}`);
  let text, rows;
  if (page === 'subscriptions') {
    text = tr('<b>Subscriptions</b>\n\nChoose the roles you want to browse and receive alerts for. Changes save immediately.\n☑ Selected · ☐ Not selected',
      '<b>اشتراک‌ها</b>\n\nموضوع‌های دلخواه برای مرور و دریافت اعلان را انتخاب کنید. تغییرها فوری ذخیره می‌شوند.\n☑ انتخاب‌شده · ☐ انتخاب‌نشده');
    rows = [[link('Academic roles', 'دانشگاهی', 'academic'), link('Career roles', 'مشاغل', 'careers')],
      [link('Life Sciences PhD', 'دکتری علوم زیستی', 'life_sciences'), link('Job markets', 'محدوده مشاغل', 'markets')],
      [link('View my matches', 'مشاهده فرصت‌های من', 'latest')]];
  } else if (['academic', 'careers', 'life_sciences', 'markets'].includes(page)) {
    const options = page === 'academic' ? ACADEMIC : page === 'careers' ? CAREERS :
      page === 'life_sciences' ? ['life_sciences_phd'] : ['iran', 'remote'];
    const field = page === 'markets' ? 'scopes' : 'topics';
    text = page === 'academic' ? tr('<b>Academic roles</b>\n\nChoose roles. Predocs are before a PhD; research staff may need a completed PhD.',
      '<b>فرصت‌های دانشگاهی</b>\n\nموضوع دلخواه را انتخاب کنید. پیشادکتری پیش از دکتری است؛ پژوهشگر حرفه‌ای ممکن است دکتری بخواهد.') :
      page === 'markets' ? tr('<b>Job markets</b>\n\nChoose one or both markets for career alerts. Academic roles are not restricted by these markets.', '<b>محدوده مشاغل</b>\n\nبرای اعلان مشاغل یک یا هر دو محدوده را انتخاب کنید. این محدوده‌ها فرصت‌های دانشگاهی را محدود نمی‌کنند.') :
      page === 'careers' ? tr('<b>Career roles</b>\n\nChoose roles, then a job market.', '<b>مشاغل</b>\n\nموضوع‌ها و سپس محدوده جستجو را انتخاب کنید.') :
      tr('<b>Life Sciences PhD · Europe</b>\n\nToggle alerts for doctoral openings.', '<b>دکتری علوم زیستی · اروپا</b>\n\nاعلان فرصت‌های دکتری را روشن یا خاموش کنید.');
    text += '\n\n' + tr('☑ Selected · ☐ Not selected · Tap to change', '☑ انتخاب‌شده · ☐ انتخاب‌نشده · برای تغییر لمس کنید');
    rows = options.map(key => [button((key in m[field] ? '☑ ' : '☐ ') +
      (key === 'iran' ? tr('Iran', 'ایران') : key === 'remote' ? tr('Worldwide remote', 'دورکاری جهانی') :
        LABELS[m.language][TOPICS.indexOf(key)]), `sub:${field === 'topics' ? 't' : 'g'}:${key}`)]);
    if (['academic', 'careers'].includes(page)) {
      const all = options.every(key => key in m.topics);
      rows.push([button(all ? tr('Clear all', 'پاک‌کردن همه') : tr('Select all', 'انتخاب همه'),
        `sub:b:${page}:${all ? 'off' : 'on'}`)]);
    }
    if (page === 'careers') rows.push([link('Choose job markets →', 'محدوده مشاغل ←', 'markets')]);
    rows.push([link('View my matches', 'مشاهده فرصت‌های من', 'latest'), link('Alert delivery', 'ارسال اعلان', 'delivery')]);
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
    text = tr('<b>Display settings</b>\n\nPositions per page. This does not change your daily alert limit.',
      '<b>تنظیمات نمایش</b>\n\nتعداد فرصت در هر صفحه. این تنظیم حد اعلان روزانه را تغییر نمی‌دهد.');
    rows = [PAGE_SIZES.slice(0, 2), PAGE_SIZES.slice(2)].map(options => options.map(n =>
      button(`${n === pageSize(size) ? '☑' : '☐'} ${n}`, `sub:n:${n}`)));
    rows.push([link('Match history: ' + lookbackLabel(selectedWindow(windowDays), false),
      'بازه مرور فرصت‌ها: ' + lookbackLabel(selectedWindow(windowDays), true), 'history')]);
  } else if (page === 'history') {
    const days = selectedWindow(windowDays);
    text = tr('<b>Match history</b>\n\nChoose how far back My matches searches. This changes browsing only, not new-job alerts or previous deliveries.',
      '<b>بازه زمانی فرصت‌ها</b>\n\nبازه جستجوی «فرصت‌های من» را انتخاب کنید. این انتخاب اعلان‌های جدید و سابقه ارسال را تغییر نمی‌دهد.');
    rows = [...lookbackChoices(days, fa, true),
      [link('View my matches →', 'مشاهده فرصت‌های من ←', 'latest')]];
  } else if (page === 'stop') {
    text = tr('<b>Unsubscribe?</b>\n\nRemove your active preferences and stop future alerts. Previously encrypted backups may remain.',
      '<b>لغو عضویت؟</b>\n\nتنظیمات فعال حذف و اعلان‌ها متوقف می‌شوند. نسخه‌های پشتیبان رمزگذاری‌شده قبلی ممکن است باقی بمانند.');
    rows = [[button(tr('Unsubscribe', 'لغو عضویت'), 'sub:stop:yes')]];
  } else if (page === 'privacy') {
    text = tr('<b>Privacy</b>\n\nYour chat ID and preferences are stored privately in Cloudflare. Scheduled alerts keep encrypted preferences and delivery records. /delete removes the active subscription; older backups may remain.',
      '<b>حریم خصوصی</b>\n\nشناسه گفت‌وگو و تنظیمات به‌صورت خصوصی در کلادفلر ذخیره می‌شوند. ارسال زمان‌بندی‌شده، تنظیمات و سوابق رمزگذاری‌شده را نگه می‌دارد. /delete اشتراک فعال را حذف می‌کند؛ پشتیبان‌های قدیمی ممکن است باقی بمانند.');
    rows = [];
  } else if (page === 'help') {
    text = tr('<b>How alerts work</b>\n\nChoose roles, then a job market for careers. Alerts cover new matches after you subscribe. Latest matches lets you browse first. Pause keeps your choices; unsubscribe removes them.\n\nMenus reply immediately. New vacancy alerts follow the collection schedule.',
      '<b>راهنما</b>\n\nموضوع‌ها و برای مشاغل محدوده را انتخاب کنید. اعلان‌ها برای فرصت‌های تازه پس از عضویت هستند. با «تازه‌ترین‌ها» مرور کنید. توقف، تنظیمات را نگه می‌دارد؛ لغو عضویت آن‌ها را حذف می‌کند.\n\nمنوها فوری پاسخ می‌دهند؛ اعلان فرصت‌ها تابع زمان گردآوری است.');
    rows = [];
  } else if (page === 'more') {
    text = tr('<b>Settings</b>', '<b>تنظیمات</b>');
    text += '\n\n' + tr('Listing size affects browsing only. Alert limits are set under Alert delivery.',
      'تعداد هر صفحه فقط برای مرور است. حد اعلان‌ها در «ارسال اعلان» تنظیم می‌شود.');
    rows = [[link('Display settings', 'تنظیمات نمایش', 'display')],
      [link('Match history: ' + lookbackLabel(selectedWindow(windowDays), false),
        'بازه فرصت‌ها: ' + lookbackLabel(selectedWindow(windowDays), true), 'history')],
      [link('Alert delivery', 'ارسال اعلان', 'delivery'), link('My matches', 'فرصت‌های من', 'latest')],
      [link('Job markets', 'محدوده مشاغل', 'markets'), link('Sources', 'منابع', 'sources')],
      [link('Help', 'راهنما', 'help'), link('Privacy', 'حریم خصوصی', 'privacy')],
      [button(fa ? 'English' : 'فارسی', `sub:l:${fa ? 'en' : 'fa'}`),
        link('Unsubscribe', 'لغو عضویت', 'stop')]];
  } else {
    const ready = ACADEMIC.some(k => k in m.topics) || 'life_sciences_phd' in m.topics ||
      (CAREERS.some(k => k in m.topics) && Object.keys(m.scopes).length > 0);
    text = '<b>Collegeum</b>\n\n' + (!ready ? tr('Choose roles to start receiving alerts.', 'برای دریافت اعلان، موضوع دلخواه را انتخاب کنید.') :
      m.paused ? tr('Alerts paused. Your choices are saved.', 'اعلان‌ها متوقف‌اند. انتخاب‌های شما ذخیره شده‌اند.') :
        tr('Alerts on for your selected roles.', 'اعلان موضوع‌های انتخاب‌شده روشن است.'));
    const chosen = TOPICS.filter(k => k in m.topics).map(k => LABELS[m.language][TOPICS.indexOf(k)]);
    if (chosen.length) text += '\n\n' + chosen.join(' · ');
    rows = [[link('My matches', 'فرصت‌های من', 'latest')],
      [link('Subscriptions', 'اشتراک‌ها', 'subscriptions'), link('Alert delivery', 'ارسال اعلان', 'delivery')],
      [link('Settings', 'تنظیمات', 'more'), link('Help', 'راهنما', 'help')]];
    if (CAREERS.some(k => k in m.topics) && !Object.keys(m.scopes).length)
      rows.splice(2, 0, [link('Choose a job market', 'محدوده مشاغل را انتخاب کنید', 'markets')]);
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
  latest: 'latest', sources: 'sources', help: 'help', more: 'more'};
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
    } else if (parts[1] === 'l' && ['en', 'fa'].includes(parts[2])) {
      m.language = parts[2]; changed = true;
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
  if (page === 'sources') content.text = (await bot.ctx.storage.get('source_status'))?.[member?.language || 'en'] ||
    (member?.language === 'fa' ? 'هنوز گزارش بررسی منابع در دسترس نیست.' : 'No source-check report is available yet.');
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
    const careers = (await bot.ctx.storage.get('career_listings') || [])
      .filter(r => matchesPreferences(r, member) && r.availability !== 'closed' &&
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
    const empty = !member || !Object.keys(member.topics || {}).length
      ? (fa ? 'ابتدا موضوع دلخواه را در اشتراک‌ها انتخاب کنید.' :
        'Choose an academic or career role in Subscriptions first.')
      : (fa ? 'در این بازه فرصت منطبق پیدا نشد. بازه ۳ ماهه یا موضوع‌های دیگر را امتحان کنید.' :
        'No matches in this window. Try 3 months or broaden your selected roles.');
    const header = (fa ? '<b>فرصت‌های من</b>' : '<b>My matches</b>') + '\n\n' +
      (fa ? 'موضوع‌ها و محدوده‌های انتخاب‌شده' : 'Your selected roles and career markets') +
      ' · ' + lookbackLabel(days, fa) + '\n' +
      (fa ? `${matches.length} مورد منطبق` : `${matches.length} matches`);
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
  if ((bot.env?.OWNER_IDS || '').split(',').map(s => s.trim()).includes(id))
    content.reply_markup.inline_keyboard.push([{text: member?.language === 'fa' ? 'پیگیری درخواست‌ها' : 'Saved & applications',
      callback_data: 'view|tracking|0'}]);
  if (callback) {
    try { await bot.api('answerCallbackQuery', {callback_query_id: callback.id}); } catch { /* expired tap */ }
  }
  await bot.deliver(key, callback ? 'editMessageText' : 'sendMessage', {
    chat_id: message.chat.id, ...(callback ? {message_id: message.message_id} : {}),
    ...content, parse_mode: 'HTML', link_preview_options: {is_disabled: true},
  });
}
