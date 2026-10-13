import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import worker, { TelegramBot, sameSecret } from './worker.mjs';

if (!globalThis.crypto) globalThis.crypto = webcrypto;

class Storage {
  values = new Map();
  tail = Promise.resolve();
  alarmAt = null;
  async getAlarm() { return this.alarmAt; }
  async setAlarm(at) { this.alarmAt = at; }
  async get(key) { return structuredClone(this.values.get(key)); }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
  async delete(key) {
    for (const k of Array.isArray(key) ? key : [key]) this.values.delete(k);
  }
  async list({prefix} = {}) {
    return new Map([...this.values].filter(([k]) => !prefix || k.startsWith(prefix)));
  }
  async transaction(fn) {
    const result = this.tail.catch(() => {}).then(async () => {
      const saved = structuredClone(this.values);
      try { return await fn(this); } catch (error) { this.values = saved; throw error; }
    });
    this.tail = result;
    return result;
  }
}
const env = {OWNER_IDS: '42', TELEGRAM_BOT_TOKEN: 'test', WEBHOOK_SECRET: 'webhook', SYNC_TOKEN: 'sync'};
const record = {url_hash: 'a'.repeat(64), title: 'Predoc in Economics', institution: 'Example University',
  apply_url: 'https://example.org/job', country: 'United Kingdom', first_seen_at: new Date().toISOString()};
const post = (path, payload) => new Request(`https://example.workers.dev${path}`, {
  method: 'POST', body: JSON.stringify(payload), headers: {'Content-Type': 'application/json'},
});
function bot() {
  const instance = new TelegramBot({storage: new Storage()}, env);
  instance.calls = [];
  instance.api = async (method, payload) => { instance.calls.push({method, payload}); return {message_id: 900}; };
  return instance;
}
const snapshot = {listings: [record], marks: {}, generated_at: new Date().toISOString()};

test('invalid AI questions consume neither public nor user quota', async () => {
  const instance = bot();
  for (const [index, text] of ['/ask', '/ask ' + 'x'.repeat(1001), 'x'.repeat(1001),
    ' '.repeat(1001) + 'x'].entries()) {
    const response = await instance.fetch(post('/webhook', {update_id: 100 + index,
      message: {chat: {id: 999, type: 'private'}, from: {id: 999}, text}}));
    assert.equal(response.status, 200);
  }
  assert.equal(instance.calls.length, 4);
  assert.equal(await instance.ctx.storage.get('rate:999'), undefined);
  assert.equal(await instance.ctx.storage.get('rate:public'), undefined);
});

test('authentication fails before durable state is allocated', async () => {
  let touched = false;
  const bindings = {...env, BOT: {get() { touched = true; }, idFromName() { touched = true; }}};
  const response = await worker.fetch(post('/webhook', {}), bindings);
  assert.equal(response.status, 401);
  assert.equal(touched, false);
  assert.equal(await sameSecret('x', 'x'), true);
  assert.equal(await sameSecret('x', 'y'), false);
  assert.equal(await sameSecret('', ''), false);
});

test('sync rejects malformed snapshots without erasing previous listings', async () => {
  const instance = bot();
  assert.equal((await instance.fetch(post('/sync', snapshot))).status, 200);
  assert.equal((await instance.fetch(post('/sync', {...snapshot, listings: [{...record, apply_url: 'javascript:alert(1)'}]}))).status, 400);
  assert.equal((await instance.dataset()).rows.length, 1);
});

test('stranger cannot query, mark or trigger outbound Telegram traffic', async () => {
  const instance = bot();
  await instance.fetch(post('/sync', snapshot));
  await instance.fetch(post('/webhook', {update_id: 1, message: {chat: {id: 999}, text: '/positions'}}));
  await instance.fetch(post('/webhook', {update_id: 2, callback_query: {id: 'cb', from: {id: 999},
    message: {chat: {id: 42}, message_id: 1}, data: `fb|v|${record.url_hash.slice(0,16)}`}}));
  assert.equal(instance.calls.length, 0);
});

test('webhook replies immediately once and replay does not toggle feedback', async () => {
  const instance = bot();
  await instance.fetch(post('/sync', snapshot));
  const update = {update_id: 1, message: {chat: {id: 42}, text: '/positions'}};
  await instance.fetch(post('/webhook', update));
  await instance.fetch(post('/webhook', update));
  assert.equal(instance.calls.filter(c => c.method === 'sendMessage').length, 1);
  const mark = {update_id: 2, callback_query: {id: 'cb', from: {id: 42},
    message: {chat: {id: 42}, message_id: 900}, data: `fb|v|${record.url_hash.slice(0,16)}`}};
  await instance.fetch(post('/webhook', mark));
  await instance.fetch(post('/webhook', mark));
  assert.equal((await instance.dataset()).marks.get(record.url_hash), 'valid');
  const undo = {...mark, update_id: 3, callback_query: {...mark.callback_query, id: 'cb2'}};
  await instance.fetch(post('/webhook', undo));
  const result = await (await instance.fetch(post('/sync', {...snapshot,
    marks: {[record.url_hash]: {status: 'valid', at: '2026-01-01T00:00:00Z'}}}))).json();
  assert.equal(result.marks[record.url_hash].status, null);
});

test('unknown delivery is not submitted again when Telegram repeats its webhook', async () => {
  const instance = bot();
  await instance.fetch(post('/sync', snapshot));
  let attempts = 0;
  instance.api = async () => { attempts++; throw new Error('unknown response'); };
  const update = {update_id: 4, message: {chat: {id: 42}, text: '/menu'}};
  await instance.fetch(post('/webhook', update));
  await instance.fetch(post('/webhook', update));
  assert.equal(attempts, 1);
  assert.equal((await instance.ctx.storage.get('update:4')).stage, 'uncertain');
});

test('search pagination retains the same query; listing text is escaped', async () => {
  const instance = bot();
  const records = Array.from({length: 6}, (_, i) => ({...record, url_hash: String(i).repeat(64), title: '<b>Economics & data</b>'}));
  await instance.fetch(post('/sync', {...snapshot, listings: records}));
  await instance.fetch(post('/webhook', {update_id: 5, message: {chat: {id: 42}, text: '/search economics'}}));
  assert.match(instance.calls[0].payload.text, /&lt;b&gt;Economics &amp; data&lt;\/b&gt;/);
  await instance.fetch(post('/webhook', {update_id: 6, callback_query: {id: 'next', from: {id: 42},
    message: {chat: {id: 42}, message_id: 900}, data: 'view|search|1'}}));
  const content = instance.calls.at(-1).payload;
  assert.match(content.text, /Page 2 of 2/);
  assert.match(content.text, /Search: economics/);
});

test('stale sync cannot replace a newer snapshot', async () => {
  const instance = bot();
  await instance.fetch(post('/sync', {...snapshot, generated_at:'2026-10-12T10:00:00Z'}));
  const result = await instance.fetch(post('/sync', {...snapshot, listings:[],
    generated_at:'2026-10-12T09:00:00Z'}));
  assert.equal(result.status,409);
  assert.equal((await instance.dataset()).rows.length,1);
});

test('slow public AI never blocks owner browsing, including the same owner chat', async () => {
  const instance = bot();
  instance.env = {...env,OPENROUTER_API_KEY:'offline-key'};
  await instance.fetch(post('/sync',snapshot));
  let release;
  const gate = new Promise(resolve => {release=resolve;});
  let entered;
  const started = new Promise(resolve => {entered=resolve;});
  const original = globalThis.fetch;
  globalThis.fetch = async () => {entered(); await gate; return Response.json({choices:[{message:{tool_calls:[{
    function:{name:'query_database',arguments:'{"action":"count"}'}
  }]}}]});};
  try {
    const accepted = await instance.fetch(post('/webhook',{update_id:10,
      message:{chat:{id:42},text:'/ask Count open roles'}}));
    assert.equal(accepted.status, 200);
    const slow = instance.alarm();
    await started;
    const menu = await instance.fetch(post('/webhook',{update_id:11,message:{chat:{id:42},text:'/menu'}}));
    assert.equal(menu.status,200);
    assert.match(instance.calls.find(c => c.method==='sendMessage').payload.text,/research shortlist/);
    release(); await slow;
  } finally {release();globalThis.fetch=original;}
});

test('concurrent public quota reservations never exceed the shared limit', async () => {
  const {reservePublic} = await import('./assistant.mjs');
  const instance=bot();instance.env.PUBLIC_HOURLY_CAP='4';
  const outcomes=await Promise.all(Array.from({length:12},(_,i)=>reservePublic(instance,i+100,false)));
  assert.equal(outcomes.filter(v=>v===null).length,4);
  assert.equal((await instance.ctx.storage.get('rate:public')).length,4);
});

test('explicit long Telegram throttling retries a prepared AI reply without repeating AI or quota', async () => {
  const instance=bot();instance.env={...env,OPENROUTER_API_KEY:'offline-key'};
  instance.api=TelegramBot.prototype.api.bind(instance);
  await instance.fetch(post('/sync',snapshot));
  let provider=0,telegram=0,throttled=true;
  const original=globalThis.fetch;
  globalThis.fetch=async url=>{
    if(String(url).includes('openrouter.ai')){
      provider++;
      return Response.json({choices:[{message:{tool_calls:[{function:{name:'query_database',arguments:'{"action":"count"}'}}]}}]});
    }
    telegram++;
    return throttled?Response.json({ok:false,parameters:{retry_after:60}},{status:429})
      :Response.json({ok:true,result:{message_id:901}});
  };
  const update={update_id:22,message:{chat:{id:123,type:'private'},from:{id:123},text:'/ask Count roles'}};
  try{
    assert.equal((await instance.fetch(post('/webhook',update))).status,200);
    assert.equal((await instance.ctx.storage.get('update:22')).stage,'queued');
    await instance.alarm();
    const prepared=await instance.ctx.storage.get('update:22');
    assert.equal(prepared.stage,'prepared');
    assert.equal((await instance.fetch(post('/webhook',update))).status,200);
    assert.equal(telegram,1);
    await instance.ctx.storage.put('update:22',{...prepared,retry_at:0});
    throttled=false;
    await instance.alarm();
    assert.equal((await instance.ctx.storage.get('update:22')).stage,'done');
    assert.equal(provider,1);assert.equal(telegram,2);
    assert.equal((await instance.ctx.storage.get('rate:public')).length,1);
  }finally{globalThis.fetch=original;}
});


test('plain-text ask with no question never reaches the provider or spends quota', async () => {
  const instance = bot();
  instance.env = {...env, OPENROUTER_API_KEY: 'offline-key'};
  let providerCalls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    providerCalls++;
    return Response.json({choices: [{message: {tool_calls: [{
      function: {name: 'query_database', arguments: '{"action":"count"}'},
    }]}}]});
  };
  try {
    const response = await instance.fetch(post('/webhook', {update_id: 240,
      message: {chat: {id: 999, type: 'private'}, from: {id: 999}, text: 'ask'}}));
    assert.equal(response.status, 200);
    assert.equal(providerCalls, 0);
    assert.equal(await instance.ctx.storage.get('rate:public'), undefined);
    assert.match(instance.calls[0].payload.text, /Try \/ask/);
  } finally {globalThis.fetch = original;}
});

test('a replaced snapshot with the same timestamp invalidates the browsing cache', async () => {
  const instance = bot();
  const at = '2026-10-13T12:00:00Z';
  assert.equal((await instance.fetch(post('/sync', {...snapshot, generated_at: at}))).status, 200);
  assert.equal((await instance.dataset()).rows[0].title, record.title);
  const fresh = {...record, title: 'Newly updated vacancy'};
  assert.equal((await instance.fetch(post('/sync', {...snapshot, generated_at: at, listings: [fresh]}))).status, 200);
  assert.equal((await instance.dataset()).rows[0].title, fresh.title);
});

test('disabled public AI does not spend quota or call the provider', async () => {
  const instance = bot();
  instance.env = {...env, OPENROUTER_API_KEY: 'offline-key', PUBLIC_AI_ENABLED: 'false'};
  let providerCalls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => {providerCalls++; throw new Error('unwanted provider call');};
  try {
    const result = await instance.fetch(post('/webhook', {update_id: 241,
      message: {chat: {id: 999, type: 'private'}, from: {id: 999}, text: '/ask Open roles'}}));
    assert.equal(result.status, 200);
    assert.equal(providerCalls, 0);
    assert.equal(await instance.ctx.storage.get('rate:public'), undefined);
    assert.match(instance.calls[0].payload.text, /available to the configured owners/);
  } finally {globalThis.fetch = original;}
});

test('an in-flight replay cannot acknowledge uncommitted Telegram delivery', async () => {
  const instance = bot();
  let start;
  const entered = new Promise(resolve => {start = resolve;});
  let finish;
  const held = new Promise(resolve => {finish = resolve;});
  instance.api = async () => {
    start();
    await held;
    throw Object.assign(new Error('Telegram rate limited'), {retryable: true, retryAfter: 60});
  };
  const update = {update_id: 242, message: {chat: {id: 42}, text: '/menu'}};
  const first = instance.fetch(post('/webhook', update));
  await entered;
  try {
    const repeat = await instance.fetch(post('/webhook', update));
    assert.equal(repeat.status, 503, 'A replay must not acknowledge an uncompleted delivery');
  } finally {finish();}
  await first;
});


test('crashed processing checkpoint is reclaimed after its lease expires', async () => {
  const instance = bot();
  const key = 'update:250';
  await instance.ctx.storage.put(key, {stage: 'processing', at: Date.now() - 91000,
    quota_reserved: true});
  const result = await instance.fetch(post('/webhook', {update_id: 250,
    message: {chat: {id: 42}, text: '/menu'}}));
  assert.equal(result.status, 200);
  assert.equal(instance.calls.length, 1);
  assert.equal((await instance.ctx.storage.get(key)).stage, 'done');
});

test('ambiguous in-flight sends return 503 until a safe replay lease expires', async () => {
  const instance = bot();
  const key = 'update:251';
  const payload = {chat_id: 42, text: 'Prepared menu'};
  await instance.ctx.storage.put(key, {stage: 'sending', at: Date.now(), method: 'sendMessage', payload});
  const update = {update_id: 251, message: {chat: {id: 42}, text: '/menu'}};
  const busy = await instance.fetch(post('/webhook', update));
  assert.equal(busy.status, 503);
  assert.equal(instance.calls.length, 0);
  await instance.ctx.storage.put(key, {stage: 'sending', at: Date.now() - 91000,
    method: 'sendMessage', payload});
  const recovered = await instance.fetch(post('/webhook', update));
  assert.equal(recovered.status, 200);
  assert.deepEqual(instance.calls[0].payload, payload);
  assert.equal((await instance.ctx.storage.get(key)).stage, 'done');
});

test('ambiguous Telegram API errors are never falsely acknowledged as delivered', async () => {
  const instance = bot();
  instance.api = async () => {throw new Error('unconfirmed delivery');};
  const key = 'update:252';
  const update = {update_id: 252, message: {chat: {id: 42}, text: '/menu'}};
  const first = await instance.fetch(post('/webhook', update));
  assert.equal(first.status, 503);
  const checkpoint = await instance.ctx.storage.get(key);
  assert.equal(checkpoint.stage, 'uncertain');
  assert.equal(checkpoint.method, 'sendMessage');
  assert.equal(checkpoint.payload.chat_id, 42);
  await instance.ctx.storage.put(key, {...checkpoint, at: Date.now() - 91000});
  instance.api = async (method, payload) => {instance.calls.push({method, payload}); return {message_id: 1};};
  const recovered = await instance.fetch(post('/webhook', update));
  assert.equal(recovered.status, 200);
  assert.equal(instance.calls.length, 1);
});

test('global AI disable gate applies to owners without invoking the provider', async () => {
  const instance = bot();
  instance.env = {...env, AI_ENABLED: 'false', OPENROUTER_API_KEY: 'offline-key'};
  const original = globalThis.fetch;
  globalThis.fetch = async () => {throw new Error('provider must not be invoked');};
  try {
    const response = await instance.fetch(post('/webhook', {update_id: 253,
      message: {chat: {id: 42}, text: '/ask Count roles'}}));
    assert.equal(response.status, 200);
    assert.match(instance.calls[0].payload.text, /currently disabled/);
    assert.equal(await instance.ctx.storage.get('rate:public'), undefined);
  } finally {globalThis.fetch = original;}
});


test('a durable alarm completes delivery after webhooks stop retrying', async () => {
  const instance = bot();
  const update = {update_id: 260, message: {chat: {id: 42}, text: '/menu'}};
  instance.api = async () => {
    throw Object.assign(new Error('rate limited'), {retryable: true, retryAfter: 3});
  };
  assert.equal((await instance.fetch(post('/webhook', update))).status, 503);
  const key = 'update:260';
  const checkpoint = await instance.ctx.storage.get(key);
  assert.equal(checkpoint.stage, 'prepared');
  assert.deepEqual(checkpoint.update, update);
  assert.ok(await instance.ctx.storage.getAlarm());
  await instance.ctx.storage.put(key, {...checkpoint, retry_at: Date.now() - 1});
  instance.api = async (method, payload) => {
    instance.calls.push({method, payload});
    return {message_id: 900};
  };
  await instance.alarm();
  assert.equal(instance.calls.length, 1);
  assert.equal((await instance.ctx.storage.get(key)).stage, 'done');
});

test('the recovery alarm also resumes crashed processing without a Telegram replay', async () => {
  const instance = bot();
  const update = {update_id: 261, message: {chat: {id: 42}, text: '/menu'}};
  await instance.ctx.storage.put('update:261', {stage: 'processing',
    at: Date.now() - 91000, update});
  await instance.alarm();
  assert.equal(instance.calls.length, 1);
  assert.equal((await instance.ctx.storage.get('update:261')).stage, 'done');
});


test('slow AI is durably queued and acknowledged before any provider call', async () => {
  const instance = bot();
  instance.env = {...env, OPENROUTER_API_KEY: 'offline-key'};
  let provider = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    provider++;
    return Response.json({choices: [{message: {tool_calls: [{
      function: {name: 'query_database', arguments: '{"action":"count"}'},
    }]}}]});
  };
  try {
    const update = {update_id: 270, message: {chat: {id: 999, type: 'private'},
      from: {id: 999}, text: '/ask Count open roles'}};
    const accepted = await instance.fetch(post('/webhook', update));
    assert.equal(accepted.status, 200);
    assert.equal(provider, 0, 'Webhook acknowledgement must not await OpenRouter');
    const pending = await instance.ctx.storage.get('update:270');
    assert.equal(pending.stage, 'queued');
    assert.deepEqual(pending.update, update);
    assert.equal((await instance.ctx.storage.get('rate:public')).length, 1);
    await instance.alarm();
    assert.equal(provider, 1);
    assert.equal(instance.calls.length, 1);
    assert.equal((await instance.ctx.storage.get('update:270')).stage, 'done');
  } finally {globalThis.fetch = original;}
});

test('replayed queued update does not reserve quota twice or enqueue twice', async () => {
  const instance = bot();
  instance.env = {...env, OPENROUTER_API_KEY: 'offline-key'};
  const update = {update_id: 271, message: {chat: {id: 123, type: 'private'},
    from: {id: 123}, text: '/ask Count roles'}};
  assert.equal((await instance.fetch(post('/webhook', update))).status, 200);
  assert.equal((await instance.fetch(post('/webhook', update))).status, 200);
  assert.equal((await instance.ctx.storage.get('rate:public')).length, 1);
  assert.equal((await instance.ctx.storage.get('update:271')).stage, 'queued');
});


test('omitted public-AI feature flag fails closed before quota or OpenRouter', async () => {
  const instance = bot();
  instance.env = {...env, PUBLIC_AI_ENABLED: undefined, OPENROUTER_API_KEY: 'offline-key'};
  const original = globalThis.fetch;
  let providerCalls = 0;
  globalThis.fetch = async () => {providerCalls++; throw new Error('unwanted network call');};
  try {
    const result = await instance.fetch(post('/webhook', {update_id: 272,
      message: {chat: {id: 222, type: 'private'}, from: {id: 222},
        text: '/ask Count research vacancies'}}));
    assert.equal(result.status, 200);
    assert.equal(providerCalls, 0);
    assert.equal(await instance.ctx.storage.get('rate:public'), undefined);
    assert.match(instance.calls[0].payload.text, /configured owners/);
  } finally {globalThis.fetch = original;}
});
