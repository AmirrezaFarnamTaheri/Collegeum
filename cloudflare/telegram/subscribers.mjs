/** Private preferences. Delivery receipts remain in the encrypted Python journal. */
import {ACADEMIC_REGIONS, REGION_LABELS, academicRegion} from './academic-regions.mjs';
export {ACADEMIC_REGIONS, academicRegion} from './academic-regions.mjs';
export const TOPICS = ['predoc', 'phd', 'postdoc', 'research', 'life_sciences_phd',
  'data_scientist', 'data_analyst', 'econ_consulting', 'research_analyst'];
const ACADEMIC = TOPICS.slice(0, 4), CAREERS = TOPICS.slice(5);
const ZONES = ['UTC', 'Asia/Tehran', 'Europe/London', 'America/New_York'];
const LIMITS = [3, 6, 10];
export const PAGE_SIZES = [4, 6, 8, 12];
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
export const matchesPreferences = (row, member) => {
  if (!member || !((row.category || row.kind) in member.topics)) return false;
  if (row.scope && !(row.scope in member.scopes)) return false;
  const regions = member.academic_regions || {};
  if (ACADEMIC.includes(row.kind || row.category) && Object.keys(regions).length)
    return 'all' in regions || academicRegion(row.country) in regions;
  return true;
};
const LABELS = {
  en: ['Predoc / research assistant', 'PhD positions', 'Postdocs', 'Research staff',
    'Life Sciences PhD · Europe', 'Data science', 'Data analysis / BI',
    'Economics consulting', 'Research / economic analysis'],
  fa: ['پیشادکتری / دستیار پژوهشی', 'فرصت دکتری', 'پسادکتری', 'پژوهشگر حرفه‌ای',
    'دکتری علوم زیستی · اروپا', 'علم داده', 'تحلیل داده / BI', 'مشاوره اقتصادی', 'تحلیل پژوهش و اقتصاد'],
};
// Two-column role controls fit small Telegram screens; the description above
// the buttons retains the distinction between predoc, PhD and staff roles.
const SHORT_ROLE_LABELS = {
  en: ['Predoc / RA', 'PhD positions', 'Postdocs', 'Research staff',
    'Life Sciences PhD', 'Data science', 'Data analysis / BI',
    'Econ consulting', 'Research analyst'],
  fa: ['پیشادکتری / دستیار', 'فرصت دکتری', 'پسادکتری', 'پژوهشگر حرفه‌ای',
    'دکتری علوم زیستی', 'علم داده', 'تحلیل داده / BI',
    'مشاوره اقتصادی', 'تحلیلگر پژوهش'],
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
// Shared visibility rule for owner browsing and subscriber matching.
export const openAcademicListing = (row, now = Date.now()) =>
  !row.closed_at && !row.expired_at && deadlineNotPassed(row.deadline, now);
const recentlyDiscovered = (value, days, now) => {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp <= now && timestamp >= now - days * 86400000;
};
const fresh = () => ({topics: {}, scopes: {}, academic_regions: {},
  paused: false, language: 'en',
  delivery_mode: 'instant', daily_limit: 6, quiet_hours: false, timezone: 'UTC'});

export function validPreferences(value) {
  if (value === null) return true;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (Object.keys(value).some(k => !Object.keys(fresh()).includes(k))) return false;
  for (const [field, allowed] of [['topics', TOPICS], ['scopes', ['iran', 'remote']],
    ['academic_regions', [...ACADEMIC_REGIONS, 'all']]]) {
    if (field === 'academic_regions' && value[field] === undefined) continue;
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
  const academicRegions = m.academic_regions || {};
  const regionNames = Object.keys(academicRegions).filter(region => region !== 'all')
    .map(region => REGION_LABELS[fa ? 'fa' : 'en'][region]);
  const regionSummary = regionNames.length ? regionNames.join(', ') :
    (fa ? 'همه جهان' : 'Worldwide');
  const tr = (en, persian) => fa ? persian : en;
  if (page === 'markets') page = 'careers'; // Keep previously sent buttons usable.
  const parent = page === 'academic_regions' ? 'academic' :
    ['academic', 'careers', 'life_sciences'].includes(page) ? 'subscriptions' :
      ['display', 'history'].includes(page) ? 'more' : 'home';
  const home = [button(parent === 'subscriptions' ? tr('← Subscriptions', '← اشتراک‌ها') :
    parent === 'more' ? tr('← Settings', '← تنظیمات') : tr('← Home', '← خانه'), `sub:p:${parent}`)];
  const link = (en, persian, page) => button(tr(en, persian), `sub:p:${page}`);
  let text, rows;
  if (page === 'subscriptions') {
    const a = ACADEMIC.filter(key => key in m.topics).length;
    const c = CAREERS.filter(key => key in m.topics).length;
    const n = Object.keys(m.scopes).length;
    const marketSummary = [
      m.scopes.iran ? tr('Iran', 'ایران') : '',
      m.scopes.remote ? tr('Remote', 'دورکاری') : '',
    ].filter(Boolean).join(' · ') || tr('Not selected', 'انتخاب نشده');
    const life = Number('life_sciences_phd' in m.topics);
    text = tr(
      '🧭 <b>Edit subscriptions</b>\n<i>Changes save as you tap.</i>\n\n' +
      `<b>🎓 Academic</b> · ${a}/4 selected\n` +
      '🌍 ' + escape(regionSummary) + '\n\n' +
      `<b>💼 Careers</b> · ${c}/4 selected\n` +
      `Job markets · ${n}/2 · ${escape(marketSummary)}\n\n` +
      `<b>🧬 Life Sciences</b> · ${life ? 'On' : 'Off'}`,
      '🧭 <b>ویرایش اشتراک‌ها</b>\n<i>هر انتخاب فوری ذخیره می‌شود.</i>\n\n' +
      `<b>🎓 دانشگاهی</b> · ${a}/۴ انتخاب‌شده\n` +
      '🌍 ' + escape(regionSummary) + '\n\n' +
      `<b>💼 مشاغل</b> · ${c}/۴ انتخاب‌شده\n` +
      `محدوده‌های شغلی · ${n}/۲ · ${escape(marketSummary)}\n\n` +
      `<b>🧬 علوم زیستی</b> · ${life ? 'فعال' : 'خاموش'}`
    );
    if (c && !n) text += tr(
      '\n\n⚠️ Choose a market to enable career matches.',
      '\n\n⚠️ برای دیدن مشاغل، یک محدوده را انتخاب کنید.');
    rows = [
      [link(`🎓 Academic · ${a}/4`, `🎓 دانشگاهی · ${a}/۴`, 'academic'),
        link(`💼 Careers · ${c}/4`, `💼 مشاغل · ${c}/۴`, 'careers')],
      [link('🧬 Life Sciences', '🧬 علوم زیستی', 'life_sciences')],
      [link('🔎 Browse my matches', '🔎 مشاهده فرصت‌ها', 'latest')],
      [link('🗓 History settings', '🗓 تنظیم بازه زمانی', 'history')],
    ];
  } else if (page === 'academic_regions') {
    const count = Object.keys(academicRegions).filter(region => region !== 'all').length;
    text = tr(
      '🌍 <b>Academic regions</b>\n<i>Choose where to look for academic roles.</i>\n\n' +
      '<b>Current:</b> ' + escape(regionSummary) + '\n' +
      `${count ? count + ' of 8 regions selected' : 'Worldwide · all locations'}\n\n` +
      'Unknown countries appear under Other / unspecified. Changing filters does not resend old alerts.',
      '🌍 <b>مناطق دانشگاهی</b>\n<i>مناطق موردنظر برای موقعیت‌های دانشگاهی را انتخاب کنید.</i>\n\n' +
      '<b>انتخاب فعلی:</b> ' + escape(regionSummary) + '\n' +
      `${count ? count + ' منطقه از ۸ منطقه' : 'همه جهان · تمام مکان‌ها'}\n\n` +
      'کشور نامشخص در گزینه «سایر» است. تغییر فیلتر پیام‌های قبلی را دوباره ارسال نمی‌کند.'
    );
    rows = [];
    for (let i = 0; i < ACADEMIC_REGIONS.length; i += 2) {
      rows.push(ACADEMIC_REGIONS.slice(i, i + 2).map(region =>
        button((region in academicRegions ? '☑ ' : '☐ ') +
          REGION_LABELS[fa ? 'fa' : 'en'][region], `sub:r:${region}`)));
    }
    rows.push([button(`${count ? '☐' : '☑'} ${tr('Worldwide · all regions', 'همه جهان · تمام مناطق')}`,
      'sub:r:all')]);
    rows.push([link('← Academic roles', '← فرصت‌های دانشگاهی', 'academic'),
      link('🔎 My matches', '🔎 فرصت‌های من', 'latest')]);
  } else if (['academic', 'careers', 'life_sciences'].includes(page)) {
    const options = page === 'academic' ? ACADEMIC :
      page === 'careers' ? CAREERS : ['life_sciences_phd'];
    const count = options.filter(key => key in m.topics).length;
    if (page === 'academic') {
      text = tr(
        '🎓 <b>Academic roles</b>\n<i>Tap to select or remove.</i>\n\n' +
        `<b>Step 1 · Roles</b>  ${count}/4 selected\n` +
        'Predoc comes before a PhD; postdocs and research staff may require one.\n\n' +
        '<b>Step 2 · Regions</b>\n🌍 ' + escape(regionSummary),
        '🎓 <b>فرصت‌های دانشگاهی</b>\n<i>برای انتخاب یا حذف ضربه بزنید.</i>\n\n' +
        `<b>مرحله ۱ · نقش‌ها</b>  ${count}/۴ انتخاب‌شده\n` +
        'پیشادکتری قبل از دکتری است؛ پسادکتری و پژوهشگر معمولاً به دکتری نیاز دارند.\n\n' +
        '<b>مرحله ۲ · مناطق</b>\n🌍 ' + escape(regionSummary));
    } else if (page === 'careers') {
      const selected = Object.keys(m.scopes).length;
      text = tr(
        '💼 <b>Career roles + markets</b>\n<i>Both are needed for career matches.</i>\n\n' +
        `<b>Step 1 · Roles</b>  ${count}/4 selected\n\n` +
        `<b>Step 2 · Job markets</b>  ${selected}/2 selected`,
        '💼 <b>مشاغل و محدوده‌ها</b>\n<i>برای دیدن مشاغل، نقش و محدوده لازم است.</i>\n\n' +
        `<b>مرحله ۱ · نقش‌ها</b>  ${count}/۴ انتخاب‌شده\n\n` +
        `<b>مرحله ۲ · محدوده‌های شغلی</b>  ${selected}/۲ انتخاب‌شده`);
      if (count && !selected) text += tr(
        '\n\n⚠️ Select Iran and/or worldwide remote to see career matches.',
        '\n\n⚠️ ایران یا دورکاری جهانی را برای دیدن مشاغل انتخاب کنید.');
    } else {
      text = tr(
        '🧬 <b>Life Sciences PhD</b>\n<i>One specialist feed · Continental Europe</i>\n\n' +
        `Status: ${count ? 'Selected' : 'Not selected'}\n` +
        'Excludes the UK. Funding and eligibility must be checked on the original advert.',
        '🧬 <b>دکتری علوم زیستی</b>\n<i>یک منبع تخصصی · اروپای قاره‌ای</i>\n\n' +
        `وضعیت: ${count ? 'انتخاب‌شده' : 'انتخاب نشده'}\n` +
        'بریتانیا شامل نمی‌شود. شرایط و تأمین مالی را در آگهی اصلی بررسی کنید.');
    }
    rows = [];
    for (let i = 0; i < options.length; i += 2) {
      rows.push(options.slice(i, i + 2).map(key =>
        button((key in m.topics ? '☑ ' : '☐ ') +
          SHORT_ROLE_LABELS[fa ? 'fa' : 'en'][TOPICS.indexOf(key)], `sub:t:${key}`)));
    }
    if (page !== 'life_sciences') {
      const all = options.every(key => key in m.topics);
      rows.push([button(all ? tr('Clear roles', 'حذف همه نقش‌ها') :
        tr('Select all roles', 'انتخاب همه نقش‌ها'),
      `sub:b:${page}:${all ? 'off' : 'on'}`)]);
    }
    if (page === 'academic') {
      rows.push([link('🌍 Edit academic regions', '🌍 انتخاب مناطق دانشگاهی',
        'academic_regions')]);
    }
    if (page === 'careers') {
      rows.push([
        button((m.scopes.iran ? '☑ ' : '☐ ') + tr('🇮🇷 Iran', '🇮🇷 ایران'), 'sub:g:iran'),
        button((m.scopes.remote ? '☑ ' : '☐ ') + tr('🌐 Remote', '🌐 دورکاری'), 'sub:g:remote'),
      ]);
    }
    rows.push([link('🔎 View matches', '🔎 مشاهده فرصت‌ها', 'latest'),
      link('🗓 History', '🗓 بازه زمانی', 'history')]);
  } else if (page === 'delivery') {
    const status = m.paused ? tr('Paused', 'متوقف') : tr('Active', 'فعال');
    text = tr(
      '🔔 <b>Alert delivery</b>\n\n' +
      '<b>Status:</b> ' + status + '\n' +
      `📬 ${m.delivery_mode === 'digest' ? 'Daily digest' : 'Individual alerts'} · max ${m.daily_limit}/day\n` +
      `🌙 Quiet hours: ${m.quiet_hours ? '22:00–08:00' : 'Off'}\n` +
      '🕓 ' + escape(m.timezone) + '\n\n' +
      '<i>New alerts follow scheduled collection, not your browsing history.</i>',
      '🔔 <b>ارسال اعلان‌ها</b>\n\n' +
      '<b>وضعیت:</b> ' + status + '\n' +
      `📬 ${m.delivery_mode === 'digest' ? 'خلاصه روزانه' : 'اعلان تکی'} · حداکثر ${m.daily_limit} در روز\n` +
      `🌙 ساعات آرام: ${m.quiet_hours ? '۲۲ تا ۸' : 'خاموش'}\n` +
      '🕓 ' + escape(m.timezone) + '\n\n' +
      '<i>اعلان‌های تازه طبق زمان‌بندی گردآوری ارسال می‌شوند، نه بازه مرور.</i>'
    );
    rows = [
      [button(tr('📬 Mode: ', '📬 روش: ') +
        (m.delivery_mode === 'digest' ? tr('Digest', 'خلاصه') : tr('Individual', 'تکی')),
      'sub:d:mode')],
      [button(tr('🎯 Daily limit: ', '🎯 سقف روزانه: ') + m.daily_limit, 'sub:d:limit')],
      [button(tr('🌙 Quiet hours: ', '🌙 ساعات آرام: ') +
        (m.quiet_hours ? tr('On', 'روشن') : tr('Off', 'خاموش')), 'sub:d:quiet')],
      [button(tr('🕓 Time zone: ', '🕓 منطقه زمانی: ') + m.timezone, 'sub:d:zone')],
      [button(m.paused ? tr('▶ Resume alerts', '▶ ازسرگیری اعلان‌ها') :
        tr('⏸ Pause alerts', '⏸ توقف اعلان‌ها'),
        m.paused ? 'sub:a:resume' : 'sub:a:pause')],
    ];
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
      + '1. Subscriptions → select Academic roles and regions, Careers with markets, or Life Sciences.\n'
      + '2. My matches → browse saved roles from the last 7, 14, 30, 60 or 90 days.\n'
      + '3. Settings → Match history saves your default range. Display controls page size.\n'
      + '4. Alert delivery → choose notification mode, quota, time zone and quiet hours.\n\n'
      + 'New alerts are only for jobs discovered after you subscribe; changing history never resends old posts. '
      + 'Collection is scheduled, so missing listings can mean an outdated snapshot. '
      + 'Always confirm eligibility and opening status on the original employer site.',
      '❔ <b>راهنمای کالجیوم</b>\n\n'
      + '۱. در اشتراک‌ها موضوع‌ها و مناطق دانشگاهی، مشاغل و محدوده‌ها یا علوم زیستی را انتخاب کنید.\n'
      + '۲. فرصت‌های من: بازه‌های ۷، ۱۴، ۳۰، ۶۰ و ۹۰ روز را مرور کنید.\n'
      + '۳. تنظیمات: بازه زمانی پیش‌فرض و تعداد نتایج در صفحه را تعیین کنید.\n'
      + '۴. ارسال اعلان: روش، سقف روزانه، منطقه زمانی و ساعات آرام را تغییر دهید.\n\n'
      + 'اعلان فقط برای فرصت‌های تازه پس از عضویت است؛ تغییر بازه موجب ارسال دوباره نمی‌شود. '
      + 'گردآوری زمان‌بندی‌شده است و ممکن است فهرست موقتاً قدیمی باشد. '
      + 'وضعیت پذیرش و شرایط را در وب‌سایت کارفرما بررسی کنید.');
    rows = [[link('🧭 Subscriptions', '🧭 اشتراک‌ها', 'subscriptions'),
      link('🗓 History settings', '🗓 بازه زمانی', 'history')]];
  } else if (page === 'more') {
    text = tr(
      '⚙️ <b>Settings</b>\n\n' +
      '<b>Browsing</b>\n' +
      `🗓 ${lookbackLabel(selectedWindow(windowDays), fa)} · 📄 ${pageSize(size)} per page\n\n` +
      '<b>Notifications</b>\n' +
      `🔔 ${m.paused ? 'Paused' : 'Active'} · ${m.daily_limit} per day\n\n` +
      '<i>Browsing settings never resend previous alerts.</i>',
      '⚙️ <b>تنظیمات</b>\n\n' +
      '<b>مرور فرصت‌ها</b>\n' +
      `🗓 ${lookbackLabel(selectedWindow(windowDays), fa)} · 📄 ${pageSize(size)} در صفحه\n\n` +
      '<b>اعلان‌ها</b>\n' +
      `🔔 ${m.paused ? 'متوقف' : 'فعال'} · ${m.daily_limit} در روز\n\n` +
      '<i>تنظیم بازه مرور باعث ارسال دوباره اعلان‌های قبلی نمی‌شود.</i>'
    );
    rows = [
      [link('🗓 Match history', '🗓 بازه زمانی', 'history'),
        link('📄 Results/page', '📄 تعداد در صفحه', 'display')],
      [link('🔔 Alert delivery', '🔔 ارسال اعلان', 'delivery'),
        link('🧭 Subscriptions', '🧭 اشتراک‌ها', 'subscriptions')],
      [link('🌐 Source status', '🌐 وضعیت منابع', 'sources'),
        link('❔ Help', '❔ راهنما', 'help')],
      [button(fa ? '🌐 English' : '🌐 فارسی', `sub:l:${fa ? 'en' : 'fa'}`),
        link('🔒 Privacy', '🔒 حریم خصوصی', 'privacy')],
      [link('🗑 Unsubscribe', '🗑 لغو اشتراک', 'stop')],
    ];
  } else {
    const nAcademic = ACADEMIC.filter(key => key in m.topics).length;
    const nCareers = CAREERS.filter(key => key in m.topics).length;
    const nLife = 'life_sciences_phd' in m.topics ? 1 : 0;
    const markets = [m.scopes.iran ? tr('Iran', 'ایران') : '',
      m.scopes.remote ? tr('Remote', 'دورکاری') : ''].filter(Boolean);
    const ready = nAcademic > 0 || nLife > 0 || (nCareers > 0 && markets.length);
    const status = !ready ? tr('Not configured', 'تنظیم نشده') :
      m.paused ? tr('Paused', 'متوقف') : tr('Active', 'فعال');
    text = tr(
      '🎯 <b>Collegeum</b>\n<i>Your career radar</i>\n\n' +
      '<b>Your search</b>\n' +
      `🎓 Academic ${nAcademic}/4 · 💼 Careers ${nCareers}/4\n` +
      `🧬 Life Sciences ${nLife ? 'On' : 'Off'}\n`,
      '🎯 <b>کالجیوم</b>\n<i>رادار فرصت‌های شما</i>\n\n' +
      '<b>جستجوی شما</b>\n' +
      `🎓 دانشگاهی ${nAcademic}/۴ · 💼 مشاغل ${nCareers}/۴\n` +
      `🧬 علوم زیستی ${nLife ? 'فعال' : 'خاموش'}\n`
    ) +
      tr('🌍 Regions: ', '🌍 مناطق: ') + escape(regionSummary.slice(0, 100)) + '\n' +
      tr('💼 Markets: ', '💼 محدوده‌ها: ') +
      escape(markets.join(' · ') || tr('Not selected', 'انتخاب نشده')) + '\n\n' +
      tr('<b>Alert status</b>\n', '<b>وضعیت اعلان‌ها</b>\n') +
      `🔔 ${status} · 🗓 ${lookbackLabel(selectedWindow(windowDays), fa)}`;
    text += '\n\n' + (!ready ? tr(
      'Choose roles under Subscriptions to personalize My matches.',
      'برای شخصی‌سازی فرصت‌ها از اشتراک‌ها موضوع انتخاب کنید.') :
      m.paused ? tr('Your choices are saved. Notifications are paused.',
        'انتخاب‌ها ذخیره شده‌اند. اعلان‌ها متوقف هستند.') :
        tr('Browse positions below. New alerts follow the collection schedule.',
          'فرصت‌های موجود را مرور کنید. اعلان‌ها طبق برنامه گردآوری ارسال می‌شوند.'));
    if (nCareers && !markets.length) text += tr(
      '\n⚠️ Career roles need a job market.',
      '\n⚠️ برای مشاغل باید محدوده انتخاب کنید.');
    rows = [
      [link('🔎 Browse my matches', '🔎 مشاهده فرصت‌های من', 'latest')],
      [link('🧭 Edit subscriptions', '🧭 ویرایش اشتراک‌ها', 'subscriptions'),
        link('🔔 Alert delivery', '🔔 ارسال اعلان', 'delivery')],
      [link('⚙️ Settings', '⚙️ تنظیمات', 'more'),
        link('❔ Help', '❔ راهنما', 'help')],
    ];
    if (nCareers && !markets.length)
      rows.splice(2, 0, [link('💼 Choose job markets', '💼 انتخاب محدوده مشاغل', 'careers')]);
    return {text, reply_markup: {inline_keyboard: rows}};
  }
  rows.push(home);
  return {text, reply_markup: {inline_keyboard: rows}};
}

const PAGES = new Set(['home', 'subscriptions', 'display', 'history', 'academic', 'academic_regions',
  'careers', 'life_sciences', 'markets', 'delivery',
  'more', 'help', 'privacy', 'stop', 'latest', 'sources']);
const COMMAND_PAGES = {start: 'home', settings: 'more', subscribe: 'subscriptions', status: 'home',
  academic: 'academic', regions: 'academic_regions', academicregions: 'academic_regions',
  careers: 'careers', markets: 'careers', lifesciences: 'life_sciences',
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
      target = field === 'scopes' ? 'careers' : option === 'life_sciences_phd' ? 'life_sciences' : ACADEMIC.includes(option) ? 'academic' : 'careers';
      changed = true;
    } else if (parts.length === 3 && parts[1] === 'r' &&
      (ACADEMIC_REGIONS.includes(parts[2]) || parts[2] === 'all')) {
      m.academic_regions ||= {};
      const region = parts[2];
      const selected = Object.keys(m.academic_regions).filter(name => name !== 'all');
      if (region === 'all') {
        // A deliberate reset to Worldwide must not make older excluded records
        // eligible for first-time alerts; its timestamp acts as an opt-in fence.
        if (selected.length) m.academic_regions = {all: new Date().toISOString()};
      } else if (region in m.academic_regions) {
        delete m.academic_regions[region];
        if (!Object.keys(m.academic_regions).length)
          m.academic_regions = {all: new Date().toISOString()};
      } else {
        delete m.academic_regions.all;
        m.academic_regions[region] = new Date().toISOString();
      }
      target = 'academic_regions'; changed = true;
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
      openAcademicListing(r, now) &&
      !['invalid', 'applied'].includes(marks?.get(r.url_hash)) &&
      recentlyDiscovered(r.first_seen_at || r.published_at, days, now) &&
      safeApplicationUrl(r.apply_url));
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
    // Twelve-result pages use a compact card to stay within Telegram's
    // 4,096-character message limit without dropping any matched positions.
    const limits = size === 12
      ? {title: 65, institution: 50, country: 24}
      : {title: 110, institution: 90, country: 50};
    const entries = matches.slice(current * size, current * size + size).map((r, index) =>
      `${current * size + index + 1}. ${r.category === 'life_sciences_phd' ? '🧬' : r.category ? '💼' : '🎓'} <a href="${escape(safeApplicationUrl(r.apply_url))}">${escape(String(r.title || 'Opportunity').slice(0, limits.title))}</a>\n` +
      '🏛 ' + escape(String(r.institution || 'Employer unknown').slice(0, limits.institution)) +
      (r.country ? ` · ${escape(String(r.country).slice(0, limits.country))}` : '') +
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
    const header = (fa ? '🔎 <b>فرصت‌های من</b>' : '🔎 <b>My matches</b>') + '\n' +
      (fa ? `<b>${matches.length} فرصت</b> · ${lookbackLabel(days, fa)}`
        : `<b>${matches.length} positions</b> · ${lookbackLabel(days, fa)}`) + '\n' +
      (fa ? `صفحه ${current + 1} از ${totalPages}` : `Page ${current + 1} of ${totalPages}`) + '\n' +
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
