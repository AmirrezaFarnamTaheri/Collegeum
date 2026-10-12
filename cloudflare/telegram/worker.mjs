/** Owner-only webhook bot. The Durable Object serializes updates and syncs. */
import {ask, reservePublic} from './assistant.mjs';
const HASH = /^[a-f0-9]{64}$/;
const STATUS = new Set(["valid", "invalid", "applied"]);
const VIEWS = new Set(["positions", "valid", "applied", "hidden", "new", "closing", "search"]);
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
  [nav("📋 Open positions", "positions"), nav("⏳ Closing soon", "closing")],
  [nav("⭐ Saved", "valid"), nav("📝 Applied", "applied")],
  [nav("🆕 New this week", "new"), nav("🙈 Hidden", "hidden")],
  [nav("🔎 Search tips", "search"), nav("❔ Help", "help")],
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
    if (request.method !== "POST" || !["/webhook", "/sync"].includes(path)) return json({error: "not found"}, 404);
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

  fetch(request) {
    return this.handle(request);
  }

  async handle(request) {
    const path = new URL(request.url).pathname;
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
    const publicChat = !callback && message?.chat?.type === 'private' &&
      Number.isSafeInteger(message?.chat?.id) && message.chat.id > 0 &&
      message.from?.id === message.chat.id;
    if (!message || (!owner && !publicChat) ||
        (callback && !owners.has(String(callback.from?.id)))) return json({ok: true, ignored: true});
    return this.processUpdate(update,callback,message,owner);
  }

  async processUpdate(update, callback, message, owner) {
    const key = `update:${update.update_id}`;
    if(this.activeUpdates.has(key))return json({ok:true,replay:true});
    this.activeUpdates.add(key);
    try{return await this.runUpdate(key,update,callback,message,owner);}
    finally{this.activeUpdates.delete(key);}
  }

  async runUpdate(key,update,callback,message,owner) {
    const claimed = await this.ctx.storage.transaction(async tx => {
      const previous=await tx.get(key);
      if(previous)return ['prepared','processing'].includes(previous.stage)?previous:false;
      await tx.put(key, {stage:'processing',at:Date.now()});
      return true;
    });
    if (!claimed) return json({ok: true, replay: true});
    try {
      if(typeof claimed==='object'&&claimed.stage==='prepared')await this.sendPrepared(key,claimed);
      else if (callback) await this.callback(callback,key);
      else {
        const input = String(message.text || '').trim();
        const word = input.split(/\s+/)[0].replace(/^\//,'').split('@')[0].toLowerCase();
        const known = new Set([...VIEWS,'menu','home','help','start','forget','saved','interested','jobs','list']);
        const ai = word === 'ask' || (!input.startsWith('/') && !known.has(word));
        if (ai) {
          // Reserve on arrival, not after waiting behind another slow AI question.
          const limited = await reservePublic(this,message.chat.id,owner,key);
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
      if(error.retryable){
        return json({error:'Telegram temporarily rejected the reply; retry later'},503);
      }
      // No raw API response or request URL enters logs; the token is in the API URL.
      await this.ctx.storage.put(key, {stage: "uncertain", at: Date.now()});
      console.warn("Telegram reply needs verification; update", update.update_id);
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
      const expired=[...recent].filter(([,v])=>v.stage==='done'&&Date.now()-v.at>48*3600000);
      if(expired.length)await this.ctx.storage.delete(expired.map(([k])=>k));
      const searches=await this.ctx.storage.list({prefix:'search:'});
      const old=[...searches].filter(([,v])=>typeof v==='string'||Date.now()-v.at>48*3600000);
      if(old.length)await this.ctx.storage.delete(old.map(([k])=>k));
    }
    return json({ok: true});
  }

  async deliver(key,method,payload){
    const prepared={stage:'prepared',at:Date.now(),method,payload};
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
      return true;
    });
    if (!replaced) return json({error:'snapshot is older than the stored inventory'},409);
    await this.ctx.storage.transaction(async tx => {
      const expiredRates = [...(await tx.list({prefix:'rate:'}))]
        .filter(([key, stamps]) => key !== 'rate:public' && Array.isArray(stamps) &&
          stamps.every(t => Date.now()-t > 60000));
      if (expiredRates.length) await tx.delete(expiredRates.map(([k]) => k));
    });
    const marks = Object.fromEntries([...(await this.ctx.storage.list({prefix: "mark:"}))]
      .map(([key, value]) => [key.slice(5), value]));
    return json({marks, snapshot_at: payload.generated_at});
  }

  async api(method, payload) {
    for(let attempt=0;attempt<3;attempt++){
    const response = await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15_000),
    });
    const result = await response.json();
    if(response.status===429){
      const raw=Number(result?.parameters?.retry_after);
      const retryAfter=Number.isFinite(raw)&&raw>=0?raw:5;
      if(attempt<2&&retryAfter<=5){await new Promise(resolve=>setTimeout(resolve,retryAfter*1000+500));continue;}
      throw Object.assign(new Error('Telegram rate limited'),{retryable:true,retryAfter});
    }
    if (!response.ok || !result?.ok) {
      if (method === "editMessageText" && response.status === 400 &&
          String(result.description).includes("message is not modified")) return;
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

  async render(kind, page = 0, query = "") {
    const {rows, marks} = await this.dataset();
    const now = Date.now();
    const open = r => !r.closed_at && !r.expired_at && (!r.deadline || Date.parse(r.deadline) >= now);
    const available = rows.filter(r => open(r) && !["invalid", "applied"].includes(marks.get(r.url_hash)));
    if (kind === "menu") return {text: '🎓 <b>Collegeum · your research shortlist</b>\n\n' +
      `<b>${available.length} open</b> · ${rows.filter(r => open(r) && marks.get(r.url_hash) === "valid").length} saved · ` +
      `${rows.filter(r => marks.get(r.url_hash) === "applied").length} applied\n\n` +
      'Browse, save promising roles, and track applications.\n🔎 <code>/search economics London</code>\n\n' +
      `Snapshot: ${esc((await this.ctx.storage.get("snapshot_at")) || "not uploaded yet")}`, reply_markup: menu()};
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
    const count = Math.max(1, Math.ceil(selected.length / 4));
    page = Math.min(Math.max(0, page), count - 1);
    const chunk = selected.slice(page * 4, page * 4 + 4);
    const labels = {positions: "Open positions", valid: "Saved", applied: "Applications", hidden: "Hidden", new: "New this week", closing: "Closing soon", search: `Search: ${query}`};
    const blocks = chunk.map((r, i) => `<b>${page * 4 + i + 1}. ${esc(r.title.slice(0, 110))}</b>\n` +
      `🏛 ${esc(r.institution.slice(0, 90))} · ${esc([r.city, r.country].filter(Boolean).join(", ").slice(0, 90) || "Location unstated")}\n` +
      `⏳ ${esc(r.deadline ? r.deadline.slice(0, 10) : r.deadline_note?.slice(0, 70) || "Deadline unstated")} · <a href="${esc(safeUrl(r.apply_url))}">Open advert</a>`);
    const buttons = chunk.map((r, i) => [
      {text: `↗ ${page * 4 + i + 1} Details`, callback_data: `detail|${r.url_hash.slice(0, 16)}`},
      ...this.feedback(r, marks.get(r.url_hash), page * 4 + i + 1),
    ]);
    const navigation = [];
    if (page) navigation.push(nav("← Previous", kind, page - 1));
    navigation.push(nav("⌂ Home", "menu"));
    if (page + 1 < count) navigation.push(nav("Next →", kind, page + 1));
    buttons.push(navigation);
    return {text: `<b>${esc(labels[kind])} · ${selected.length}</b>\n\n` +
      (blocks.join("\n\n") || "No matches. Try another view or search.") +
      `\n\nPage ${page + 1} of ${count} · Dates shown as supplied by the advert`, reply_markup: {inline_keyboard: buttons}};
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
    kind = aliases[kind] || kind;
    const naturalQuestion = !word.startsWith('/') && !VIEWS.has(kind) && !['menu','help'].includes(kind);
    if (kind === 'forget') {
      await this.ctx.storage.delete(`query:${message.chat.id}`);
      await this.deliver(updateKey,'sendMessage', {chat_id:message.chat.id, text:'Your AI follow-up context is cleared. Rate limits still apply.'});
      return;
    }
    if (kind === 'ask' || naturalQuestion) {
      const question = naturalQuestion ? String(message.text || '') : words.join(' ');
      const text = admission.limited || await ask(this,question,message.chat.id,owner,admission.admitted,updateKey);
      await this.deliver(updateKey,'sendMessage', {chat_id:message.chat.id,text,parse_mode:'HTML',
        ...(owner ? {reply_markup:menu()} : {}),link_preview_options:{is_disabled:true}});
      return;
    }
    if (!owner) {
      await this.deliver(updateKey,'sendMessage',{chat_id:message.chat.id,text:'Ask about stored research vacancies with /ask. Public users can ask 3 questions per minute, within a shared hourly cap. Personal tracking is private to the owners.'});
      return;
    }
    if (!VIEWS.has(kind) && !["menu", "help"].includes(kind)) kind = "help";
    const query = kind === "search" ? words.join(" ").slice(0, 160) : "";
    const content = await this.render(kind, 0, query);
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
      if (!VIEWS.has(kind) && !["menu", "help"].includes(kind)) return;
      const storedSearch=kind==='search'?await this.ctx.storage.get(`search:${message.chat.id}:${message.message_id}`):null;
      const query=typeof storedSearch==='string'?storedSearch:storedSearch?.query||'';
      content = await this.render(kind, Number(parts[2]), query);
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
