/** Run the bundled Worker in workerd with real SQLite DO storage; all egress is mocked. */
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import test from 'node:test';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';

test('workerd validates webhook auth, SQLite snapshots, private feedback and public AI quotas', async () => {
  const calls=[];
  const mf=new Miniflare(convertV4MiniflareOptions({
    modules:true,scriptPath:resolve('.wrangler/build/worker.js'),compatibilityDate:'2026-10-12',
    durableObjects:{BOT:{className:'TelegramBot',useSQLite:true}},
    bindings:{OWNER_IDS:'42',TELEGRAM_BOT_TOKEN:'offline-token',WEBHOOK_SECRET:'offline-webhook',
      SYNC_TOKEN:'offline-sync',OPENROUTER_API_KEY:'offline-openrouter',PUBLIC_HOURLY_CAP:'4',
      PUBLIC_AI_ENABLED:'true'},
    outboundService:async request => {
      const url=new URL(request.url);
      assert.ok(['api.telegram.org','openrouter.ai'].includes(url.hostname));
      const body=await request.json();calls.push({url:url.pathname,body});
      if(url.hostname==='openrouter.ai')return Response.json({choices:[{message:{tool_calls:[{
        function:{name:'query_database',arguments:'{"action":"count"}'},
      }]}}]});
      return Response.json({ok:true,result:{message_id:900}});
    },
  }));
  const send=async(path,body,authorized=true)=>mf.dispatchFetch(`https://worker.example${path}`,{
    method:'POST',headers:{'Content-Type':'application/json',...(authorized ? path==='/sync'
      ? {'Authorization':'Bearer offline-sync'}:{'X-Telegram-Bot-Api-Secret-Token':'offline-webhook'}:{})},
    body:JSON.stringify(body),
  });
  try {
    assert.equal((await send('/webhook',{},false)).status,401);
    const row={id:42,url_hash:'a'.repeat(64),kind:'predoc',title:'Economics RA',institution:'Example University',
      country:'Canada',apply_url:'https://example.org/job',first_seen_at:new Date().toISOString()};
    const snapshot={listings:[row],marks:{},generated_at:new Date().toISOString(),
      subscriber_protocol:1,subscribers:{}};
    assert.equal((await send('/sync',snapshot)).status,200);
    assert.equal((await send('/sync',{...snapshot,listings:[],generated_at:'2026-10-11T00:00:00Z'})).status,409);
    await send('/webhook',{update_id:1,message:{chat:{id:42},text:'/menu'}});
    assert.match(calls.find(c=>c.url.endsWith('/sendMessage')).body.text,/Choose roles/);
    await send('/webhook',{update_id:2,callback_query:{id:'callback',from:{id:42},
      message:{chat:{id:42},message_id:900},data:'fb|v|'+row.url_hash.slice(0,16)}});
    const marked=await (await send('/sync',snapshot)).json();
    assert.equal(marked.marks[row.url_hash].status,'valid');
    const preference = {update_id:3,callback_query:{id:'subscriber-choice',from:{id:777},
      message:{chat:{id:777,type:'private'},message_id:901},data:'sub:t:predoc'}};
    assert.equal((await send('/webhook',preference)).status,200);
    assert.equal((await send('/webhook',preference)).status,200);
    const choices=await (await send('/sync',snapshot)).json();
    assert.ok(choices.subscribers['777'].topics.predoc);
    assert.equal(calls.filter(c=>c.url.endsWith('/editMessageText')&&c.body.chat_id===777).length,1);
    // Full runtime path: Python-shaped academic snapshot -> saved role -> match panel.
    const myMatches = {update_id:4, callback_query:{id:'matching-roles',from:{id:777},
      message:{chat:{id:777,type:'private'},message_id:901},data:'sub:p:latest'}};
    assert.equal((await send('/webhook',myMatches)).status,200);
    const view = calls.filter(c=>c.url.endsWith('/editMessageText')&&c.body.chat_id===777).at(-1);
    assert.match(view.body.text, /Economics RA/);
    assert.match(view.body.text, /last 14 days/i);
    assert.equal((await mf.dispatchFetch('https://worker.example/status')).status,401);
    const status=await (await mf.dispatchFetch('https://worker.example/status',{
      headers:{Authorization:'Bearer offline-sync'},
    })).json();
    assert.equal(status.subscribers_initialized,true);
    assert.equal(status.subscribers,undefined);
    assert.deepEqual(status.inventory_counts, {academic: 1, career: 0});
    // Distinct valid IDs execute concurrently against the actual DO transaction API.
    await Promise.all(Array.from({length:6},(_,i)=>send('/webhook',{update_id:100+i,
      message:{chat:{id:1000+i,type:'private'},from:{id:1000+i},text:'/ask Count open roles'}})));
    // AI is performed by Durable Object alarms after the webhook has been
    // acknowledged, rather than during its HTTP request.
    for (let i = 0; i < 100; i++) {
      if (calls.filter(c=>c.url==='/api/v1/chat/completions').length === 4 &&
          calls.some(c=>c.body.text?.includes('shared hourly'))) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.equal(calls.filter(c=>c.url==='/api/v1/chat/completions').length,4);
    assert.ok(calls.some(c=>c.body.text?.includes('shared hourly')));
  } finally {await mf.dispose();}
});
