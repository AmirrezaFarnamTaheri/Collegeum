/** Owner-only webhook bot. The Durable Object serializes updates and syncs. */
import {ask, reservePublic} from './assistant.mjs';
import {subscriberCommand, subscriberUpdate, validPreferences, matchesPreferences, pageSize, panel} from './subscribers.mjs';
const HASH = /^[a-f0-9]{64}$/;
const STATUS = new Set(["valid", "invalid", "applied"]);
const VIEWS = new Set(["positions", "valid", "applied", "hidden", "new", "closing", "search"]);
const COMMANDS = new Set([...VIEWS, 'menu', 'more', 'home', 'help', 'start', 'forget', 'saved',
  'interested', 'jobs', 'list', 'tracking']);
const aiQuestion = message => {
  const input = String(message.text || '').trim();
  const word = input.split(/\s+/)[0].replace(/^\//, '').split('@')[0].toLowerCase();
  if (word === 'ask') return input.split(/\s+/).slice(1).join(' ');
  return !input.startsWith('/') && !COMMANDS.has(word) && !subscriberCommand(word)
    ? String(message.text || '') : null;
};
const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
const json = (body, status = 200) => Response.json(body, {status, headers: {"Cache-Control": "no-store"}});
const nav = (text, kind, page = 0) => ({text, callback_data: `view|${kind}|${page}`});
const ownerIds = env => new Set((env.OWNER_IDS || "").split(",").map(s => s.trim()).filter(s => /^[1-9]\d*$/.test(s)));
const safeUrl = value => {
  try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) && !u.username && !u.password ? u.href : ""; }
  catch { return ""; }
};
const menu = () => ({inline_keyboard: [
  [nav('Saved', 'valid'), nav('Applied', 'applied')],
  [nav('Academic matches', 'positions'), nav('Closing soon', 'closing')],
  [nav('Search', 'search'), nav('More', 'more')],
  [nav('← Home', 'menu')],
]});
const moreMenu = () => ({inline_keyboard: [
  [nav("🆕 New this week", "new"), nav("🙈 Hidden", "hidden")],
  [nav("❔ Help", "help"), nav("← Home", "menu")],
  [{text: 'Alert settings', callback_data: 'sub:p:home'}],
]});

export async function sameSecret(actual, expected) {
  if (!actual || !expected) return false;
  const encoder = new TextEncoder();
  const [a, b] = await Promise.all([actual, expected].map(s => crypto.subtle.digest("SHA-256", encoder.encode(s))));
  const left = new Uint8Array(a), right = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === "/health" && request.method === "GET") return json({service: "collegeum-telegram"});
    if (!(request.method === 'GET' && path === '/status') &&
        (request.method !== "POST" || !["/webhook", "/sync"].includes(path))) return json({error: "not found"}, 404);
    if (!env.TELEGRAM_BOT_TOKEN || !env.WEBHOOK_SECRET || !env.SYNC_TOKEN || !ownerIds(env).size)
      return json({error: "service not configured"}, 503);
    const authenticated = path === "/webhook"
      ? await sameSecret(request.headers.get("X-Telegram-Bot-Api-Secret-Token"), env.WEBHOOK_SECRET)
      : await sameSecret(request.headers.get("Authorization"), `Bearer ${env.SYNC_TOKEN}`);
    if (!authenticated) return json({error: "unauthorized"}, 401);
    // Secrets are validated before allocating or querying durable state.
    const stub = env.BOT.get(env.BOT.idFromName("owner-bot"));
    return stub.fetch(request);
  },
};

export class TelegramBot {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; this.chatTails = new Map(); this.activeUpdates=new Set(); }

  async scheduleRecovery(at) {
    const storage = this.ctx.storage;
    if (typeof storage.getAlarm !== 'function' || typeof storage.setAlarm !== 'function') return;
    const existing = await storage.getAlarm();
    if (existing === null || existing > at) await storage.setAlarm(at);
  }

  async alarm() {
    // Telegram abandons non-2xx webhooks after a finite number of retries.
    // Alarms keep unfinished replies recoverable even without another request.
    const readyAt = state => Math.max(
      ['prepared', 'queued'].includes(state.stage) ? 0 : (state.at || 0) + 90000,
      state.retry_at || 0,
    );
    const pending = [...(await this.ctx.storage.list({prefix: 'update:'}))]
      .filter(([,state]) => !['done', 'rejected'].includes(state?.stage) && state?.update);
    let attempted = 0;
    for (const [key, state] of pending) {
      if (attempted >= 4) break;
      if (readyAt(state) > Date.now() || this.activeUpdates.has(key)) continue;
      const update = state.update;
      const callback = update.callback_query;
      const message = callback?.message || update.message;
      if (!message) continue;
      attempted++;
      const owner = ownerIds(this.env).has(String(message.chat?.id));
      try { await this.processUpdate(update,callback,message,owner); }
      catch { console.warn('Failed to recover durable Telegram update',update.update_id); }
    }
    const waiting = [...(await this.ctx.storage.list({prefix: 'update:'}))]
      .filter(([,state]) => !['done', 'rejected'].includes(state?.stage) && state?.update);
    if (waiting.length) {
      const next = Math.min(...waiting.map(([,state]) => readyAt(state)));
      await this.scheduleRecovery(Math.max(Date.now() + 1000, next));
    }
  }

  fetch(request) {
    return this.handle(request);
  }

  async handle(request) {
    const path = new URL(request.url).pathname;
    if (path === '/status' && request.method === 'GET') {
      const updates = [...(await this.ctx.storage.list({prefix: 'update:'})).values()];
      return json({subscriber_protocol: 1,
        subscribers_initialized: Boolean(await this.ctx.storage.get('subscribers_initialized')),
        snapshot_at: await this.ctx.storage.get('snapshot_at') || null,
        pending_updates: updates.filter(s => !['done', 'rejected'].includes(s.stage)).length});
    }
    let payload;
    try {
      if (Number(request.headers.get("Content-Length") || 0) > 2_000_000) return json({error: "too large"}, 413);
      const text = await request.text();
      if (new TextEncoder().encode(text).length > 2_000_000) return json({error: "too large"}, 413);
      payload = JSON.parse(text);
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error();
    } catch { return json({error: "invalid JSON"}, 400); }
    if (path === "/sync") return this.sync(payload);
    if (path !== "/webhook") return json({error: "not found"}, 404);
    const update = payload;
    if (!Number.isSafeInteger(update.update_id) || update.update_id < 0) return json({error: "invalid update"}, 400);
    const callback = update.callback_query;
    const message = callback?.message || update.message;
    const owners = ownerIds(this.env);
    const owner = owners.has(String(message?.chat?.id));
    const publicChat = message?.chat?.type === 'private' &&
      Number.isSafeInteger(message?.chat?.id) && message.chat.id > 0 &&
      (callback?.from?.id ?? message.from?.id) === message.chat.id;
    if (!message || (!owner && !publicChat) ||
        (callback && !owners.has(String(callback.from?.id)) &&
          !(publicChat && String(callback.data || '').startsWith('sub:')))) return json({ok: true, ignored: true});
    const question = callback ? null : aiQuestion(message);
    if (question !== null && question.trim() && question.length <= 1000 &&
        this.env.AI_ENABLED !== 'false' && (owner || this.env.PUBLIC_AI_ENABLED === 'true'))
      return this.queueAI(update,message,owner);
    return this.processUpdate(update,callback,message,owner);
  }

  async processUpdate(update, callback, message, owner) {
    const key = `update:${update.update_id}`;
    if(this.activeUpdates.has(key))return json({error:'Update is still processing; retry later'},503);
    this.activeUpdates.add(key);
    try{return await this.runUpdate(key,update,callback,message,owner);}
    finally{this.activeUpdates.delete(key);}
  }

  async queueAI(update,message,owner) {
    // Acknowledge the webhook only after an inbox record is durable and
    // public quota is reserved. The provider and Telegram calls run by alarm.
    const key = `update:${update.update_id}`;
    const created = await this.ctx.storage.transaction(async tx => {
      if (await tx.get(key)) return false;
      await tx.put(key, {stage: 'queued', at: Date.now(), update});
      return true;
    });
    if (created) await reservePublic(this,message.chat.id,owner,key);
    await this.scheduleRecovery(Date.now() + 5);
    return json({ok: true, queued: true, replay: !created});
  }

  async runUpdate(key,update,callback,message,owner) {
    const claimed = await this.ctx.storage.transaction(async tx => {
      const previous=await tx.get(key);
      if (previous) {
        if (previous.stage === 'prepared') return previous;
        if (['done', 'rejected'].includes(previous.stage)) return false;
        if (previous.stage === 'queued') {
          await tx.put(key, {...previous, stage: 'processing', at: Date.now()});
          return true;
        }
        if (Date.now() - previous.at < 90000) return null;
        if (['sending', 'uncertain'].includes(previous.stage) && previous.method &&
            previous.payload) {
          // At-least-once recovery: an interrupted Telegram call may duplicate a
          // message. Never acknowledge ambiguous delivery without retrying it.
          return {...previous, stage: 'prepared'};
        }
        // A crashed processor may have already persisted quota, AI results or
        // feedback. Preserve these checkpoints when reclaiming its update.
        const resumed = {...previous, stage: 'processing', at: Date.now()};
        await tx.put(key, resumed);
        return true;
      }
      await tx.put(key, {stage:'processing',at:Date.now(),update});
      return true;
    });
    if (claimed) await this.scheduleRecovery(Date.now() + 90000);
    if (claimed === null) return json({error:'Update is still processing; retry later'},503);
    if (!claimed) return json({ok: true, replay: true});
    try {
      if(typeof claimed==='object'&&claimed.stage==='prepared')await this.sendPrepared(key,claimed);
      else if (callback && String(callback.data || '').startsWith('sub:'))
        await subscriberUpdate(this,message,callback,key);
      else if (callback) await this.callback(callback,key);
      else {
        const question = aiQuestion(message);
        if (question !== null) {
          // Reserve on arrival, not after waiting behind another slow AI question.
          // Invalid input gets its guidance reply without charging either quota.
          const enabled = this.env.AI_ENABLED !== 'false';
          const publicEnabled = this.env.PUBLIC_AI_ENABLED === 'true';
          const limited = !enabled || (!owner && !publicEnabled) ||
            !question.trim() || question.length > 1000 ? null
            : await reservePublic(this,message.chat.id,owner,key);
          const chat = String(message.chat.id);
          const previous = this.chatTails.get(chat) || Promise.resolve();
          const result = previous.catch(() => {}).then(() => this.command(message,owner,{limited,admitted:true},key));
          this.chatTails.set(chat,result);
          try { await result; }
          finally { if (this.chatTails.get(chat) === result) this.chatTails.delete(chat); }
        } else await this.command(message,owner,{},key);
      }
      await this.ctx.storage.put(key, {stage: "done", at: Date.now()});
    } catch(error) {
      if(error.permanent){
        // Definitive API rejections are not retryable. Drop the private
        // payload while retaining a terminal receipt for webhook replays.
        const saved = await this.ctx.storage.get(key) || {};
        await this.ctx.storage.put(key,{stage:'rejected',at:Date.now(),
          status:error.status,method:saved.method || 'unknown'});
        console.warn('Telegram operation permanently rejected',update.update_id,error.status);
        return json({ok:true,rejected:true});
      }
      if(error.retryable){
        return json({error:'Telegram temporarily rejected the reply; retry later'},503);
      }
      // Preserve prepared payload and checkpoints across crashes. Do not emit
      // a successful webhook acknowledgement when delivery was not verified.
      const saved = await this.ctx.storage.get(key);
      await this.ctx.storage.put(key, {...saved, stage: "uncertain", at: Date.now()});
      console.warn("Telegram reply needs verification; update", update.update_id);
      return json({error:'Telegram delivery unconfirmed; retry later'},503);
    }
    const clean=await this.ctx.storage.transaction(async tx=>{
      const last=await tx.get('cleanup_at')||0;
      if(Date.now()-last<3600000)return false;
      await tx.put('cleanup_at',Date.now());return true;
    });
    // Telegram retains unread updates for 24h. Retain replay protection for 48h,
    // rather than evicting a valid claim merely because traffic exceeded 1,000.
    if(clean){
      const recent=await this.ctx.storage.list({prefix:'update:'});
      const expired=[...recent].filter(([,v])=>['done','rejected'].includes(v.stage)&&Date.now()-v.at>48*3600000);
      if(expired.length)await this.ctx.storage.delete(expired.map(([k])=>k));
      const searches=await this.ctx.storage.list({prefix:'search:'});
      const old=[...searches].filter(([,v])=>typeof v==='string'||Date.now()-v.at>48*3600000);
      if(old.length)await this.ctx.storage.delete(old.map(([k])=>k));
    }
    return json({ok: true});
  }

  async deliver(key,method,payload){
    const checkpoint = await this.ctx.storage.get(key) || {};
    const prepared={...checkpoint,stage:'prepared',at:Date.now(),method,payload};
    await this.ctx.storage.put(key,prepared);
    return this.sendPrepared(key,prepared);
  }

  async sendPrepared(key,prepared){
    if(prepared.retry_at>Date.now())throw Object.assign(new Error('retry later'),{retryable:true});
    await this.ctx.storage.put(key,{...prepared,stage:'sending'});
    try{return await this.api(prepared.method,prepared.payload);}
    catch(error){
      if(error.retryable){
        await this.ctx.storage.put(key,{...prepared,retry_at:Date.now()+Math.max(1000,error.retryAfter*1000)});
      }
      throw error;
    }
  }

  async sync(payload) {
    const listings = payload.listings;
    if (!Array.isArray(listings) || listings.length > 2000 || !payload.generated_at ||
        !Number.isFinite(Date.parse(payload.generated_at))) return json({error: "invalid snapshot"}, 400);
    const keys = new Set();
    for (const r of listings) {
      if (!r || !HASH.test(r.url_hash) || keys.has(r.url_hash) || typeof r.title !== "string" ||
          typeof r.institution !== "string" || !safeUrl(r.apply_url) ||
          JSON.stringify(r).length > 16_000) return json({error: "invalid listing"}, 400);
      keys.add(r.url_hash);
    }
    const initialMarks = payload.marks || {};
    if (!initialMarks || Array.isArray(initialMarks) || typeof initialMarks !== "object" ||
        Object.keys(initialMarks).length > 2000) return json({error: "invalid marks"}, 400);
    for (const [hash, mark] of Object.entries(initialMarks)) {
      if (!HASH.test(hash) || !mark || !STATUS.has(mark.status) || !Number.isFinite(Date.parse(mark.at)))
        return json({error: "invalid mark"}, 400);
    }
    const subscribers = payload.subscribers || {};
    const careers = payload.career_listings || [];
    const sourceStatus = payload.source_status || {};
    if (!sourceStatus || typeof sourceStatus !== 'object' || Array.isArray(sourceStatus) ||
        Object.entries(sourceStatus).some(([lang, text]) => !['en', 'fa'].includes(lang) ||
          typeof text !== 'string' || text.length > 4000)) return json({error: 'invalid source status'}, 400);
    if (!Array.isArray(careers) || careers.length > 2000 || careers.some(r =>
      !r || typeof r.title !== 'string' || typeof r.employer !== 'string' || !safeUrl(r.url) ||
      typeof r.category !== 'string' || typeof r.scope !== 'string' ||
      !Number.isFinite(Date.parse(r.first_seen_at)) || JSON.stringify(r).length > 16000))
      return json({error: 'invalid career snapshot'}, 400);
    if (payload.subscriber_protocol !== undefined && payload.subscriber_protocol !== 1)
      return json({error: 'unsupported subscriber protocol'}, 400);
    if (!subscribers || typeof subscribers !== 'object' || Array.isArray(subscribers) ||
        Object.keys(subscribers).length > 1000 || Object.entries(subscribers).some(([id, member]) =>
          !/^[1-9]\d{0,15}$/.test(id) || !validPreferences(member)))
      return json({error: 'invalid subscriber preferences'}, 400);
    const replaced = await this.ctx.storage.transaction(async tx => {
      const previous = await tx.get('snapshot_at');
      if (previous && Date.parse(previous) > Date.parse(payload.generated_at)) return false;
      const current = await tx.list({prefix: "listing:"});
      for (const [key] of current) if (!keys.has(key.slice(8))) await tx.delete(key);
      for (const row of listings) await tx.put(`listing:${row.url_hash}`, row);
      // Local marks seed the worker once. Thereafter the webhook owns feedback,
      // including explicit null tombstones for undo; stale CI state cannot resurrect it.
      if (!await tx.get("initialized")) {
        for (const [hash, mark] of Object.entries(initialMarks)) await tx.put(`mark:${hash}`, mark);
        await tx.put("initialized", true);
      }
      await tx.put("snapshot_at", payload.generated_at);
      await tx.put('career_listings', careers);
      await tx.put('source_status', sourceStatus);
      if (payload.subscriber_protocol === 1 && !await tx.get('subscribers_initialized')) {
        for (const [id, member] of Object.entries(subscribers)) await tx.put(`subscriber:${id}`, member);
        await tx.put('subscribers_initialized', true);
      }
      return true;
    });
    if (!replaced) return json({error:'snapshot is older than the stored inventory'},409);
    this.cachedDataset = null;
    await this.ctx.storage.transaction(async tx => {
      const expiredRates = [...(await tx.list({prefix:'rate:'}))]
        .filter(([key, stamps]) => key !== 'rate:public' && Array.isArray(stamps) &&
          stamps.every(t => Date.now()-t > 60000));
      if (expiredRates.length) await tx.delete(expiredRates.map(([k]) => k));
    });
    const marks = Object.fromEntries([...(await this.ctx.storage.list({prefix: "mark:"}))]
      .map(([key, value]) => [key.slice(5), value]));
    const profiles = Object.fromEntries([...(await this.ctx.storage.list({prefix: 'subscriber:'}))]
      .map(([key, value]) => [key.slice('subscriber:'.length), value]));
    return json({marks, snapshot_at: payload.generated_at, subscriber_protocol: 1, subscribers: profiles});
  }

  async api(method, payload) {
    const acknowledgement = method === 'answerCallbackQuery';
    for(let attempt=0;attempt<(acknowledgement ? 1 : 3);attempt++){
    const response = await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      signal: AbortSignal.timeout(acknowledgement ? 2000 : 15_000),
    });
    const result = await response.json();
    if(response.status===429){
      if (acknowledgement) throw new Error('Callback acknowledgement unavailable');
      const raw=Number(result?.parameters?.retry_after);
      const retryAfter=Number.isFinite(raw)&&raw>=0?raw:5;
      if(attempt<2&&retryAfter<=5){await new Promise(resolve=>setTimeout(resolve,retryAfter*1000+500));continue;}
      throw Object.assign(new Error('Telegram rate limited'),{retryable:true,retryAfter});
    }
    if (!response.ok || !result?.ok) {
      if (method === "editMessageText" && response.status === 400 &&
          String(result.description).includes("message is not modified")) return;
      if ([400, 403, 422].includes(response.status)) {
        throw Object.assign(new Error('Telegram permanently rejected the operation'),
          {permanent:true,status:response.status});
      }
      throw new Error("Telegram operation failed");
    }
    return result.result;
    }
    throw new Error('Telegram operation failed');
  }

  async dataset(owner=true) {
    const version=await this.ctx.storage.get('snapshot_at');
    if(!this.cachedDataset||this.cachedDataset.version!==version){
      this.cachedDataset=await this.ctx.storage.transaction(async tx=>({
        version:await tx.get('snapshot_at'),rows:[...(await tx.list({prefix:'listing:'})).values()],
      }));
    }
    const rows=this.cachedDataset.rows;
    const marks = new Map(owner?[...(await this.ctx.storage.list({prefix: "mark:"}))]
      .map(([k, v]) => [k.slice(5), v.status]):[]);
    return {rows, marks};
  }

  async render(kind, page = 0, query = "", chatId = null) {
    const {rows, marks} = await this.dataset();
    const member = chatId === null ? null : await this.ctx.storage.get(`subscriber:${chatId}`);
    const size = pageSize(chatId === null ? null : await this.ctx.storage.get(`page_size:${chatId}`));
    const now = Date.now();
    const open = r => !r.closed_at && !r.expired_at && (!r.deadline || Date.parse(r.deadline) >= now);
    const available = rows.filter(r => open(r) && !["invalid", "applied"].includes(marks.get(r.url_hash)) &&
      matchesPreferences(r, member));
    if (kind === 'menu') {
      const content = panel(member, 'home', size);
      content.reply_markup.inline_keyboard.push([nav('Saved & applications', 'tracking')]);
      return content;
    }
    if (kind === "tracking") return {text: '<b>Saved & applications</b>\n\n' +
      `<b>${available.length} academic matches</b> · ${rows.filter(r => open(r) && marks.get(r.url_hash) === "valid").length} saved · ` +
      `${rows.filter(r => marks.get(r.url_hash) === "applied").length} applied\n\n` +
      'Search with <code>/search economics London</code>.\n\n' +
      `Listings updated: ${esc((await this.ctx.storage.get("snapshot_at")) || "Waiting for first sync")}`, reply_markup: menu()};
    if (kind === "more") return {text: '⚙️ <b>More options</b>\n\n' +
      'View recent or hidden positions, or open help.', reply_markup: moreMenu()};
    if (kind === "help" || (kind === "search" && !query)) return {text:
      '🎓 <b>Collegeum bot</b>\n\n/menu · /positions · /saved · /applied · /hidden\n' +
      '/new: added this week · /closing: deadlines within 7 days\n' +
      '🔎 <code>/search economics London</code>: all words must match.\n\n' +
      '✅ Save · ❌ Hide · 📝 Applied. Tap again to undo.\n' +
      'Replies use the latest uploaded snapshot. Check the original advert before applying.', reply_markup: menu()};
    let selected = ["valid", "applied", "hidden"].includes(kind)
      ? rows.filter(r => marks.get(r.url_hash) === (kind === "hidden" ? "invalid" : kind) && (kind !== "valid" || open(r)))
      : available;
    if (kind === "closing") selected = selected.filter(r => r.deadline && Date.parse(r.deadline) <= now + 7 * 86400000);
    if (kind === "new") selected = selected.filter(r => Date.parse(r.first_seen_at) >= now - 7 * 86400000 && Date.parse(r.first_seen_at) <= now);
    if (kind === "search") selected = selected.filter(r => query.toLowerCase().split(/\s+/).every(term =>
      [r.title, r.institution, r.country, r.city, r.summary, r.principal_investigator].join(" ").toLowerCase().includes(term)));
    selected.sort((a, b) => kind === "new" ? Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at) :
      (Date.parse(a.deadline) || Infinity) - (Date.parse(b.deadline) || Infinity) || a.title.localeCompare(b.title));
    const count = Math.max(1, Math.ceil(selected.length / size));
    page = Math.min(Math.max(0, page), count - 1);
    const chunk = selected.slice(page * size, page * size + size);
    const labels = {positions: "My academic matches", valid: "Saved", applied: "Applications", hidden: "Hidden", new: "New academic matches", closing: "Academic matches closing soon", search: `Search my academic matches: ${query}`};
    const blocks = chunk.map((r, i) => `<b>${page * size + i + 1}. ${esc(r.title.slice(0, 110))}</b>\n` +
      `🏛 ${esc(r.institution.slice(0, 90))} · ${esc([r.city, r.country].filter(Boolean).join(", ").slice(0, 90) || "Location unstated")}\n` +
      `⏳ ${esc(r.deadline ? r.deadline.slice(0, 10) : r.deadline_note?.slice(0, 70) || "Deadline unstated")} · <a href="${esc(safeUrl(r.apply_url))}">Open advert</a>`);
    const buttons = chunk.map((r, i) => [
      {text: `↗ ${page * size + i + 1} Details`, callback_data: `detail|${r.url_hash.slice(0, 16)}`},
      ...this.feedback(r, marks.get(r.url_hash), page * size + i + 1),
    ]);
    const navigation = [];
    if (page) navigation.push(nav("← Previous", kind, page - 1));
    navigation.push(nav("⌂ Home", "menu"));
    if (page + 1 < count) navigation.push(nav("Next →", kind, page + 1));
    buttons.push(navigation);
    buttons.push([{text: 'Edit subscriptions', callback_data: 'sub:p:subscriptions'},
      {text: `Page size: ${size}`, callback_data: 'sub:p:display'}]);
    return {text: `<b>${esc(labels[kind])} · ${selected.length}</b>\n\n` +
      (blocks.join("\n\n") || (kind === 'valid' ? 'No saved positions yet. Open a position and tap Save.' :
        kind === 'search' ? 'No matches. Try fewer words or a different location.' :
          'No matches in this view. Review your subscriptions or check again later.')) +
      (count > 1 ? `\n\nPage ${page + 1} of ${count}` : ''), reply_markup: {inline_keyboard: buttons}};
  }

  feedback(row, status, number = "") {
    return [["v", "valid", "✅"], ["x", "invalid", "❌"], ["a", "applied", "📝"]].map(([code, st, icon]) =>
      ({text: `${st === status ? "• " : ""}${icon} ${number || ({valid: "Save", invalid: "Hide", applied: "Applied"})[st]}`,
        callback_data: `fb|${code}|${row.url_hash.slice(0, 16)}`}));
  }

  async command(message, owner = true, admission = {}, updateKey) {
    const [word, ...words] = String(message.text || "/menu").trim().split(/\s+/);
    const aliases = {start: "menu", home: "menu", saved: "valid", interested: "valid", jobs: "positions", list: "positions"};
    let kind = word.replace(/^\//, "").split("@")[0].toLowerCase();
    if ((subscriberCommand(kind) && (kind !== 'start' || !owner)) ||
        (!owner && ['help', 'more', 'menu', 'home'].includes(kind))) {
      await subscriberUpdate(this,message,null,updateKey);
      return;
    }
    kind = aliases[kind] || kind;
    const naturalQuestion = !word.startsWith('/') && kind !== 'ask' && !VIEWS.has(kind) && !['menu','help','more','tracking'].includes(kind);
    if (kind === 'forget') {
      await this.ctx.storage.delete(`query:${message.chat.id}`);
      await this.deliver(updateKey,'sendMessage', {chat_id:message.chat.id, text:'Your AI follow-up context is cleared. Rate limits still apply.'});
      return;
    }
    if (kind === 'ask' || naturalQuestion) {
      const question = naturalQuestion ? String(message.text || '') : words.join(' ');
      const text = this.env.AI_ENABLED === 'false'
        ? 'Database chat is currently disabled.'
        : !owner && this.env.PUBLIC_AI_ENABLED !== 'true'
          ? 'Database chat is currently available to the configured owners.'
          : admission.limited || await ask(this,question,message.chat.id,owner,
            admission.admitted && Boolean(question.trim()) && question.length <= 1000,updateKey);
      await this.deliver(updateKey,'sendMessage', {chat_id:message.chat.id,text,parse_mode:'HTML',
        ...(owner ? {reply_markup:menu()} : {}),link_preview_options:{is_disabled:true}});
      return;
    }
    if (!owner) {
      await this.deliver(updateKey,'sendMessage',{chat_id:message.chat.id,text:'Ask about stored research vacancies with /ask. Public users can ask 3 questions per minute, within a shared hourly cap. Personal tracking is private to the owners.'});
      return;
    }
    if (!VIEWS.has(kind) && !["menu", "help", "more", "tracking"].includes(kind)) kind = "help";
    const query = kind === "search" ? words.join(" ").slice(0, 160) : "";
    const content = await this.render(kind, 0, query, message.chat.id);
    const result = await this.deliver(updateKey,"sendMessage", {chat_id: message.chat.id, ...content, parse_mode: "HTML",
      link_preview_options: {is_disabled: true}});
    if (kind === "search" && query && Number.isSafeInteger(result?.message_id))
      await this.ctx.storage.put(`search:${message.chat.id}:${result.message_id}`, {query,at:Date.now()});
  }

  async callback(callback,updateKey) {
    try { await this.api("answerCallbackQuery", {callback_query_id: callback.id}); } catch { /* stale toast */ }
    const parts = String(callback.data || "").split("|");
    const message = callback.message;
    let content;
    if (parts[0] === "view" && parts.length === 3 && /^\d{1,6}$/.test(parts[2])) {
      const kind = parts[1];
      if (!VIEWS.has(kind) && !["menu", "help", "more", "tracking"].includes(kind)) return;
      const storedSearch=kind==='search'?await this.ctx.storage.get(`search:${message.chat.id}:${message.message_id}`):null;
      const query=typeof storedSearch==='string'?storedSearch:storedSearch?.query||'';
      content = await this.render(kind, Number(parts[2]), query, message.chat.id);
    } else if ((parts[0] === "fb" && parts.length === 3) || (parts[0] === "detail" && parts.length === 2)) {
      const prefix = parts.at(-1);
      if (!/^[a-f0-9]{16}$/.test(prefix)) return;
      const matches = [...(await this.ctx.storage.list({prefix: `listing:${prefix}`})).values()];
      if (matches.length !== 1) return;
      const row = matches[0];
      if (parts[0] === "fb") {
        const status = ({v: "valid", x: "invalid", a: "applied"})[parts[1]];
        if (!status) return;
        await this.ctx.storage.transaction(async tx => {
          const claim=await tx.get(updateKey);
          if(claim?.feedback_applied)return;
          const previous = await tx.get(`mark:${row.url_hash}`);
          await tx.put(`mark:${row.url_hash}`, {status: previous?.status === status ? null : status,
            at: new Date().toISOString(), title: row.title, institution: row.institution, url: row.apply_url});
          await tx.put(updateKey,{...claim,feedback_applied:true});
        });
      }
      const mark = await this.ctx.storage.get(`mark:${row.url_hash}`);
      content = {text: `<b>${esc(row.title.slice(0, 200))}</b>\n🏛 ${esc(row.institution.slice(0, 180))}\n` +
        `${esc([row.city, row.country].filter(Boolean).join(", ").slice(0, 180))}\n\n` +
        `⏳ ${esc(row.deadline?.slice(0, 10) || row.deadline_note?.slice(0, 200) || "Deadline unstated")}\n` +
        `${esc(row.summary?.slice(0, 900) || "See the original advert for requirements.")}\n\n` +
        `Visa: ${esc(row.visa_note?.slice(0, 300) || "Unstated; check advert")}\n` +
        (row.closed_at || row.expired_at ? "⚠️ This advert is now closed.\n" : "") +
        `<a href="${esc(safeUrl(row.apply_url))}">Open official advert ↗</a>`,
        reply_markup: {inline_keyboard: [[{text: "Open advert ↗", url: safeUrl(row.apply_url)}],
          this.feedback(row, mark?.status), [nav("← Open positions", "positions"), nav("⌂ Home", "menu")]]}};
    } else return;
    await this.deliver(updateKey,"editMessageText", {chat_id: message.chat.id, message_id: message.message_id,
      ...content, parse_mode: "HTML", link_preview_options: {is_disabled: true}});
  }
}
