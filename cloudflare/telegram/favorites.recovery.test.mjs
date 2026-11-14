import assert from 'node:assert/strict';
import test from 'node:test';
import {TelegramBot} from './worker.mjs';

class Storage {
  values = new Map();
  tail = Promise.resolve();
  async get(key) { return structuredClone(this.values.get(key)); }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
  async delete(keys) {
    for (const key of Array.isArray(keys) ? keys : [keys]) this.values.delete(key);
  }
  async list({prefix} = {}) {
    return new Map([...this.values].filter(([key]) => !prefix || key.startsWith(prefix)));
  }
  async transaction(fn) {
    const result = this.tail.catch(() => {}).then(async () => {
      const snapshot = structuredClone(this.values);
      try { return await fn(this); } catch (error) { this.values = snapshot; throw error; }
    });
    this.tail = result;
    return result;
  }
}
const message = {chat:{id:997,type:'private'},message_id:77};
const tap = (id, action) => ({
  update_id:id, callback_query:{id:String(id),from:{id:997},message,data:action},
});
const makeBot = () => {
  const bot = new TelegramBot({storage:new Storage()}, {
    OWNER_IDS:'42', TELEGRAM_BOT_TOKEN:'test', WEBHOOK_SECRET:'test', SYNC_TOKEN:'test',
  });
  bot.calls = [];
  bot.api = async (method,payload) => {bot.calls.push({method,payload});return {message_id:900};};
  return bot;
};
const key = 'a'.repeat(16);

test('atomic delete checkpoint prevents recovery from erasing a new favorite and subscription', async () => {
  const bot = makeBot(), update = tap(94001,'fav:delete:yes');
  await bot.ctx.storage.put('favorite:997:'+key,{saved_at:'2026-01-01T00:00:00Z'});
  await bot.ctx.storage.put('subscriber:997',{topics:{predoc:'2026-01-01T00:00:00Z'}});
  const original = bot.favoriteRows.bind(bot);
  let failOnce = true;
  bot.favoriteRows = async (...args) => {
    if (failOnce) {failOnce=false;throw new Error('render crashed after commit');}
    return original(...args);
  };
  let result = await bot.processUpdate(update,update.callback_query,message,false);
  assert.equal(result.status,503);
  assert.equal((await bot.ctx.storage.get('update:94001')).favorite_mutation_applied,true);
  assert.equal((await bot.ctx.storage.list({prefix:'favorite:997:'})).size,0);
  await bot.ctx.storage.put('favorite:997:'+key,{saved_at:'2026-02-01T00:00:00Z'});
  await bot.ctx.storage.put('subscriber:997',{topics:{career:'2026-02-01T00:00:00Z'}});
  const saved=await bot.ctx.storage.get('update:94001');
  await bot.ctx.storage.put('update:94001',{...saved,at:Date.now()-91000});
  result=await bot.processUpdate(update,update.callback_query,message,false);
  assert.equal(result.status,200);
  assert.equal((await bot.ctx.storage.list({prefix:'favorite:997:'})).size,1);
  assert.ok((await bot.ctx.storage.get('subscriber:997')).topics.career);
});

test('atomic favorite removal checkpoint does not remove a re-saved bookmark on retry', async () => {
  const bot=makeBot(), update=tap(94002,'fav:remove:'+key);
  await bot.ctx.storage.put('favorite:997:'+key,{saved_at:'2026-01-01T00:00:00Z'});
  const original=bot.favoriteRows.bind(bot);
  let failOnce=true;
  bot.favoriteRows=async (...args)=>{
    if(failOnce){failOnce=false;throw new Error('read failed after removal');}
    return original(...args);
  };
  assert.equal((await bot.processUpdate(update,update.callback_query,message,false)).status,503);
  await bot.ctx.storage.put('favorite:997:'+key,{saved_at:'2026-02-01T00:00:00Z'});
  const saved=await bot.ctx.storage.get('update:94002');
  await bot.ctx.storage.put('update:94002',{...saved,at:Date.now()-91000});
  assert.equal((await bot.processUpdate(update,update.callback_query,message,false)).status,200);
  assert.equal((await bot.ctx.storage.list({prefix:'favorite:997:'})).size,1);
});
