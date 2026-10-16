/** Private preferences. Delivery receipts remain in the encrypted Python journal. */
export const TOPICS = ['predoc', 'phd', 'postdoc', 'research', 'life_sciences_phd',
  'data_scientist', 'data_analyst', 'econ_consulting', 'research_analyst'];
const ACADEMIC = TOPICS.slice(0, 4), CAREERS = TOPICS.slice(5);
const ZONES = ['UTC', 'Asia/Tehran', 'Europe/London', 'America/New_York'];
const LIMITS = [3, 6, 10];
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

export function panel(member, page = 'home') {
  const m = member || fresh(), fa = m.language === 'fa';
  const tr = (en, persian) => fa ? persian : en;
  const home = [button(tr('← Home', '← خانه'), 'sub:p:home')];
  const link = (en, persian, page) => button(tr(en, persian), `sub:p:${page}`);
  let text, rows;
  if (['academic', 'careers', 'life_sciences', 'markets'].includes(page)) {
    const options = page === 'academic' ? ACADEMIC : page === 'careers' ? CAREERS :
      page === 'life_sciences' ? ['life_sciences_phd'] : ['iran', 'remote'];
    const field = page === 'markets' ? 'scopes' : 'topics';
    text = page === 'academic' ? tr('<b>Academic roles</b>\n\nChoose roles. Predocs are before a PhD; research staff may need a completed PhD.',
      '<b>فرصت‌های دانشگاهی</b>\n\nموضوع دلخواه را انتخاب کنید. پیشادکتری پیش از دکتری است؛ پژوهشگر حرفه‌ای ممکن است دکتری بخواهد.') :
      page === 'markets' ? tr('<b>Job markets</b>\n\nChoose one or both markets for career alerts.', '<b>محدوده مشاغل</b>\n\nبرای اعلان مشاغل یک یا هر دو محدوده را انتخاب کنید.') :
      page === 'careers' ? tr('<b>Career roles</b>\n\nChoose roles, then a job market.', '<b>مشاغل</b>\n\nموضوع‌ها و سپس محدوده جستجو را انتخاب کنید.') :
      tr('<b>Life Sciences PhD · Europe</b>\n\nToggle alerts for doctoral openings.', '<b>دکتری علوم زیستی · اروپا</b>\n\nاعلان فرصت‌های دکتری را روشن یا خاموش کنید.');
    rows = options.map(key => [button((key in m[field] ? '✓ ' : '○ ') +
      (key === 'iran' ? tr('Iran', 'ایران') : key === 'remote' ? tr('Worldwide remote', 'دورکاری جهانی') :
        LABELS[m.language][TOPICS.indexOf(key)]), `sub:${field === 'topics' ? 't' : 'g'}:${key}`)]);
    if (['academic', 'careers'].includes(page)) {
      const all = options.every(key => key in m.topics);
      rows.push([button(all ? tr('Clear all', 'پاک‌کردن همه') : tr('Select all', 'انتخاب همه'),
        `sub:b:${page}:${all ? 'off' : 'on'}`)]);
    }
    if (page === 'careers') rows.push([link('Choose job markets →', 'محدوده مشاغل ←', 'markets')]);
  } else if (page === 'delivery') {
    text = tr('<b>Alert delivery</b>', '<b>ارسال اعلان‌ها</b>') + '\n\n' +
      tr('Changes apply at the next scheduled alert run. Individual alerts are sent when new matches are collected.',
        'تغییرات در اجرای بعدی ارسال اعمال می‌شوند. اعلان تکی پس از گردآوری فرصت تازه ارسال می‌شود.');
    rows = [[button(tr('Mode: ', 'روش: ') + (m.delivery_mode === 'digest' ? tr('Daily digest', 'خلاصه روزانه') : tr('Individual', 'تکی')), 'sub:d:mode')],
      [button(tr('Daily maximum: ', 'حد روزانه: ') + m.daily_limit, 'sub:d:limit')],
      [button(tr('Quiet hours: ', 'ساعات آرام: ') + (m.quiet_hours ? '22:00–08:00' : tr('Off', 'خاموش')), 'sub:d:quiet')],
      [button(tr('Time zone: ', 'منطقه زمانی: ') + m.timezone, 'sub:d:zone')]];
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
    rows = [[link('Job markets', 'محدوده مشاغل', 'markets'), link('Sources', 'منابع', 'sources')],
      [link('Help', 'راهنما', 'help'), link('Privacy', 'حریم خصوصی', 'privacy')],
      [button(fa ? 'English' : 'فارسی', `sub:l:${fa ? 'en' : 'fa'}`),
        link('Unsubscribe', 'لغو عضویت', 'stop')]];
  } else {
    const ready = ACADEMIC.some(k => k in m.topics) || 'life_sciences_phd' in m.topics ||
      (CAREERS.some(k => k in m.topics) && Object.keys(m.scopes).length > 0);
    text = '<b>Collegeum</b>\n\n' + (!ready ? tr('Choose roles to start receiving alerts.', 'برای دریافت اعلان، موضوع دلخواه را انتخاب کنید.') :
      m.paused ? tr('Alerts paused. Your choices are saved.', 'اعلان‌ها متوقف‌اند. انتخاب‌های شما ذخیره شده‌اند.') :
        tr('Alerts on for your selected roles.', 'اعلان موضوع‌های انتخاب‌شده روشن است.'));
    rows = [[link('Academic roles', 'دانشگاهی', 'academic'), link('Career roles', 'مشاغل', 'careers')],
      [link('Life Sciences PhD', 'دکتری علوم زیستی', 'life_sciences')],
      [link('Latest matches', 'تازه‌ترین‌ها', 'latest'), link('Alert delivery', 'ارسال اعلان', 'delivery')],
      [button(m.paused ? tr('Resume alerts', 'ازسرگیری اعلان') : tr('Pause alerts', 'توقف اعلان'),
        m.paused ? 'sub:a:resume' : 'sub:a:pause'), link('Settings', 'تنظیمات', 'more')]];
    if (CAREERS.some(k => k in m.topics) && !Object.keys(m.scopes).length)
      rows.splice(2, 0, [link('Choose a job market', 'محدوده مشاغل را انتخاب کنید', 'markets')]);
    return {text, reply_markup: {inline_keyboard: rows}};
  }
  rows.push(home);
  return {text, reply_markup: {inline_keyboard: rows}};
}

const PAGES = new Set(['home', 'academic', 'careers', 'life_sciences', 'markets', 'delivery',
  'more', 'help', 'privacy', 'stop', 'latest', 'sources']);
const COMMAND_PAGES = {start: 'home', settings: 'home', subscribe: 'home', status: 'home',
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
  const page = await bot.ctx.storage.transaction(async tx => {
    const claim = await tx.get(key);
    if (claim?.subscriber_applied) return claim.subscriber_page;
    const old = await tx.get(`subscriber:${id}`), m = old || fresh();
    let target = 'home', changed = false;
    const parts = raw.split(':');
    if (parts[1] === 'p' && PAGES.has(parts[2])) target = parts[2];
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
      m.paused = parts[2] === 'pause'; changed = true;
    } else if (parts[1] === 'd' && old) {
      const fields = {mode: ['delivery_mode', ['instant', 'digest']], limit: ['daily_limit', LIMITS],
        zone: ['timezone', ZONES], quiet: ['quiet_hours', [false, true]]};
      if (!fields[parts[2]]) return 'home';
      const [field, options] = fields[parts[2]];
      m[field] = options[(options.indexOf(m[field]) + 1) % options.length];
      target = 'delivery'; changed = true;
    } else if (raw === 'sub:stop:yes') {
      await tx.put(`subscriber:${id}`, null);
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
  let content = panel(member, page);
  if (page === 'full') content.text = 'Subscriptions are full. Please try again later.';
  if (page === 'sources') content.text = (await bot.ctx.storage.get('source_status'))?.[member?.language || 'en'] ||
    (member?.language === 'fa' ? 'هنوز گزارش بررسی منابع در دسترس نیست.' : 'No source-check report is available yet.');
  if (page === 'latest') {
    const {rows} = await bot.dataset(false);
    const recent = at => Number.isFinite(Date.parse(at)) && Date.parse(at) >= Date.now() - 14 * 86400000;
    const academic = rows.filter(r => member && r.kind in member.topics && !r.closed_at && !r.expired_at &&
      recent(r.published_at) && (!r.deadline || Date.parse(r.deadline) >= Date.now()));
    const careers = (await bot.ctx.storage.get('career_listings') || []).filter(r => member &&
      r.category in member.topics && (!r.scope || r.scope in member.scopes) &&
      r.availability !== 'closed' && recent(r.first_seen_at)).map(r => ({
        ...r, apply_url: r.url, institution: r.employer, published_at: r.first_seen_at,
      }));
    const matches = [...academic, ...careers].sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at)).slice(0, 40);
    const fa = member?.language === 'fa';
    const totalPages = Math.max(1, Math.ceil(matches.length / 4));
    const current = Math.min(totalPages - 1, /^sub:p:latest:\d{1,6}$/.test(raw) ? Number(raw.split(':')[3]) : 0);
    content = {text: (fa ? '<b>تازه‌ترین‌ها</b>' : '<b>Latest matches</b>') + '\n\n' +
      (matches.slice(current * 4, current * 4 + 4).map(r => `<a href="${escape(r.apply_url)}">${escape(r.title.slice(0, 110))}</a>\n${escape(r.institution.slice(0, 90))}`).join('\n\n') ||
        (fa ? 'موردی یافت نشد. موضوع‌ها را تغییر دهید یا بعداً بررسی کنید.' : 'No matches yet. Change your roles or check again later.')),
      reply_markup: {inline_keyboard: [
        ...(totalPages > 1 ? [[...(current ? [button('‹', `sub:p:latest:${current - 1}`)] : []),
          button(`${current + 1}/${totalPages}`, `sub:p:latest:${current}`),
          ...(current + 1 < totalPages ? [button('›', `sub:p:latest:${current + 1}`)] : [])]] : []),
        [button(fa ? '← خانه' : '← Home', 'sub:p:home')]]}};
  }
  if (callback) {
    try { await bot.api('answerCallbackQuery', {callback_query_id: callback.id}); } catch { /* expired tap */ }
  }
  await bot.deliver(key, callback ? 'editMessageText' : 'sendMessage', {
    chat_id: message.chat.id, ...(callback ? {message_id: message.message_id} : {}),
    ...content, parse_mode: 'HTML', link_preview_options: {is_disabled: true},
  });
}
