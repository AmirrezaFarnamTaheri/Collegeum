import protocol from '../../config/telegram-assistant.json' with {type: 'json'};

export const refusal = 'I can query stored research vacancies, deadlines, employers, locations, pay, qualifications and stated visa terms. I cannot answer unrelated questions, predict openings, decide personal eligibility or invent missing facts.';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[c]);

export function validateQuery(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('invalid query');
  const properties = protocol.tool.function.parameters.properties;
  if (!properties.action.enum.includes(input.action)) throw new Error('invalid action');
  for (const [key, value] of Object.entries(input)) {
    const schema = properties[key];
    if (!schema) throw new Error('unknown query field');
    if (schema.enum && !schema.enum.includes(value)) throw new Error('invalid enum');
    if (schema.type === 'string' && (typeof value !== 'string' || value.length > (schema.maxLength || 1000))) throw new Error('invalid string');
    if (schema.type === 'integer' && (!Number.isSafeInteger(value) || value < schema.minimum || value > schema.maximum)) throw new Error('invalid integer');
    if (schema.type === 'array') {
      if (!Array.isArray(value) || value.length > schema.maxItems) throw new Error('invalid array');
      if (schema.items.enum && value.some(v => !schema.items.enum.includes(v))) throw new Error('invalid fields');
      if (schema.items.type === 'integer' && value.some(v => !Number.isSafeInteger(v) || v < 1)) throw new Error('invalid IDs');
    }
    if (schema.format === 'date' && (!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0,10) !== value)) throw new Error('invalid date');
  }
  if (input.deadline_after && input.deadline_before && input.deadline_after > input.deadline_before) throw new Error('invalid date range');
  return {query:'', country:'', institution:'', degree:'', kind:'', visa:'', personal_status:'',
    status:'open', ids:[], group_by:'country', fields:['deadline'], limit:4, ...input};
}

export function queryRecords(query, rows, marks, owner, now = Date.now()) {
  if (query.personal_status && !owner) throw new Error('private marks');
  return rows.filter(r => {
    const deadline = Date.parse(r.deadline);
    const closed = r.closed_at || r.expired_at || deadline < now;
    if (query.status === 'open' && closed || query.status === 'closed' && !closed) return false;
    if (query.ids.length && !query.ids.includes(r.id)) return false;
    if (query.personal_status && marks.get(r.url_hash) !== query.personal_status) return false;
    if ([['country',query.country],['institution',query.institution],['min_degree',query.degree]].some(([k,v]) => v && !String(r[k] || '').toLowerCase().includes(v.toLowerCase()))) return false;
    if (query.kind && r.kind !== query.kind || query.visa && (r.visa || 'unknown') !== query.visa) return false;
    const text = [r.title,r.institution,r.country,r.city,r.summary,r.disciplines].join(' ').toLowerCase();
    if (query.query.toLowerCase().split(/\s+/).some(word => !text.includes(word))) return false;
    const date = r.deadline?.slice(0,10);
    if (query.deadline_after && (!date || date < query.deadline_after) ||
        query.deadline_before && (!date || date > query.deadline_before)) return false;
    return true;
  }).sort((a,b) => String(a.deadline || '9999').localeCompare(String(b.deadline || '9999')) || a.id - b.id);
}

export function renderAnswer(query, rows, snapshot) {
  if (query.action === 'refuse') return refusal;
  const head = `📚 <b>Database result · ${rows.length} matching record(s)</b>\n\n`;
  const foot = `\n\nStored snapshot: ${escape(snapshot || 'not uploaded')}. Facts are not a live eligibility decision; unstated facts remain unknown.`;
  if (query.action === 'count') return head + 'Count computed from stored records and requested filters.' + foot;
  if (!rows.length) return head + 'No matching stored records. This does not establish that no such vacancy exists.' + foot;
  if (query.action === 'group') {
    const counts = new Map();
    for (const row of rows) { const k = row[query.group_by] || 'Unstated'; counts.set(k, (counts.get(k) || 0) + 1); }
    return head + [...counts].sort((a,b) => b[1]-a[1]).slice(0,20).map(([k,v]) => `${escape(String(k).slice(0,100))}: ${v}`).join('\n') + foot;
  }
  const blocks = [];
  for (const row of rows.slice(0,query.limit)) {
    const values = {deadline:row.deadline || row.deadline_note, visa:`${row.visa || 'unknown'} · ${row.visa_note || 'No supporting note stored'}`,
      salary:row.salary_raw, degree:row.degree_note || row.min_degree, tools:(row.tools_required || []).join(', '),
      start:row.start_term || row.start_date, summary:row.summary};
    const block = `<b>#${row.id} · ${escape(row.title.slice(0,140))}</b>\n${escape(row.institution.slice(0,120))}\n` +
      [...new Set(query.fields)].map(field => `${field}: ${escape(String(values[field] || 'Unstated').slice(0,180))}`).join('\n') +
      `\n<a href="${escape(row.apply_url)}">Source advert ↗</a>`;
    // Bound HTML bytes conservatively, preserving complete tags and source links.
    if (new TextEncoder().encode(head + blocks.join('\n\n') + block + foot).length > 3900) break;
    blocks.push(block);
  }
  return head + blocks.join('\n\n') + `\n\nShowing ${blocks.length} of ${rows.length} matching records. Ask for specific IDs to see omitted details.` + foot;
}

export async function reservePublic(instance, userId, owner, updateKey) {
  if (owner) return null;
  const storage = instance.ctx.storage;
  const now = Date.now();
  const cap = Number(instance.env.PUBLIC_HOURLY_CAP || 100);
  if (!Number.isSafeInteger(cap) || cap < 1 || cap > 10000) return 'Database AI is temporarily unavailable.';
  return storage.transaction(async tx => {
    const claim=updateKey?await tx.get(updateKey):null;
    if(claim?.quota_reserved)return claim.quota_denial||null;
    const user = (await tx.get(`rate:${userId}`) || []).filter(t => now - t < 60000 && t <= now);
    const global = (await tx.get('rate:public') || []).filter(t => now - t < 3600000 && t <= now);
    const denial=user.length>=3?'You can ask 3 questions per minute. Try again in a moment.':
      global.length>=cap?'The shared hourly AI limit has been reached. Try again later.':null;
    if(updateKey)await tx.put(updateKey,{...claim,quota_reserved:true,quota_denial:denial});
    if(denial)return denial;
    await tx.put(`rate:${userId}`, [...user,now]);
    await tx.put('rate:public', [...global,now]);
    return null;
  });
}

export async function ask(instance, question, userId, owner, admitted = false, updateKey) {
  const prepared=updateKey?await instance.ctx.storage.get(updateKey):null;
  if(prepared?.ai_result)return prepared.ai_result;
  if (!question.trim()) return '📚 Try /ask Which economics roles close this month?';
  if (question.length > 1000) return 'Please keep your database question under 1,000 characters.';
  const keys = [...new Set([instance.env.OPENROUTER_API_KEY, instance.env.OPENROUTER_API_KEYS].filter(Boolean).join(',').split(/[,;\s]+/).filter(Boolean))];
  if (!keys.length) return 'Database chat is not configured yet. OpenRouter must be connected.';
  const storage = instance.ctx.storage;
  const now = Date.now();
  if (!admitted) {
    const limited = await reservePublic(instance,userId,owner);
    if (limited) return limited;
  }
  const previous = (await storage.get(`query:${userId}`))?.query;
  const body = {model:instance.env.OPENROUTER_MODEL || 'openrouter/free', max_tokens:600, temperature:0,
    messages:[{role:'system',content:protocol.system + `\nUTC date: ${new Date().toISOString().slice(0,10)}.\n` +
      (owner ? '' : 'Personal marks are private and unavailable to this user.')},
    {role:'user',content:JSON.stringify({question,previous_query:previous || null})}],
    tools:[protocol.tool],tool_choice:{type:'function',function:{name:'query_database'}}};
  try {
    let query;
    const deadline = Date.now() + 25000;
    for (const key of keys.slice(0,5)) {
      const remaining = deadline-Date.now();
      if (remaining <= 0) break;
      const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {method:'POST',
        headers:{'Authorization':`Bearer ${key}`,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(Math.min(20000,remaining))});
      if (response.status === 429) continue;
      if (!response.ok) return 'Database AI is temporarily unavailable. Your tracking marks are unchanged.';
      const data = await response.json();
      const calls = data.choices?.[0]?.message?.tool_calls;
      if (!Array.isArray(calls) || calls.length !== 1 || calls[0].function?.name !== 'query_database') return refusal;
      query = validateQuery(JSON.parse(calls[0].function.arguments));
      break;
    }
    if (!query) return 'The AI provider is busy. Please try again later.';
    if (query.action === 'refuse') return refusal;
    const {rows,marks} = await instance.dataset(owner);
    const result = queryRecords(query,rows,owner ? marks : new Map(),owner);
    await storage.put(`query:${userId}`,{query,at:now});
    const histories = await storage.list({prefix:'query:'});
    if (histories.size > 500) {
      const oldest = [...histories].sort((a,b) => a[1].at - b[1].at).slice(0,histories.size-500);
      await storage.delete(oldest.map(([k]) => k));
    }
    const answer=renderAnswer(query,result,await storage.get('snapshot_at'));
    if(updateKey)await storage.transaction(async tx=>{
      const claim=await tx.get(updateKey);await tx.put(updateKey,{...claim,ai_result:answer});
    });
    return answer;
  } catch { return refusal; }
}
