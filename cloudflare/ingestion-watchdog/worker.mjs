/** Independent fail-closed ingestion recovery observer (no public trigger). */
const REPO = 'AmirrezaFarnamTaheri/Collegeum';
const API = 'https://api.github.com/repos/' + REPO;
const MAX_STALENESS = 8 * 60 * 60 * 1000;
const MAX_CLOCK_SKEW = 2 * 60 * 1000;
const ACTIVE = new Set(['queued', 'requested', 'waiting', 'pending', 'in_progress']);
const KNOWN = new Set([...ACTIVE, 'completed']);

function timestamp(value) {
  if (typeof value !== 'string' || !value.includes('T') ||
      !/(?:Z|[+-]\d\d:\d\d)$/.test(value)) return NaN;
  return Date.parse(value);
}

const rejected = reason => ({dispatch: false, reason});

/** Pure gate: mirror the in-repository Python watchdog's duplicate safety. */
export function decide(health, runs, nowMs = Date.now()) {
  if (!Number.isFinite(nowMs)) return rejected('untrusted-clock');
  const generated = timestamp(health?.generated_at);
  if (!Number.isFinite(generated)) return rejected('invalid-health-timestamp');
  if (generated > nowMs + MAX_CLOCK_SKEW) return rejected('future-health-timestamp');
  if (nowMs - generated <= MAX_STALENESS) return rejected('fresh');
  if (!Array.isArray(runs) || runs.length === 0) return rejected('untrusted-run-history');
  let foundMain = false;
  let running = false;
  let newer = false;
  for (const run of runs) {
    if (!run || typeof run !== 'object' || Array.isArray(run)) {
      return rejected('untrusted-run-history');
    }
    if (run.head_branch !== 'main') continue;
    foundMain = true;
    const created = timestamp(run.created_at);
    if (!Number.isFinite(created) || created > nowMs + MAX_CLOCK_SKEW ||
        !KNOWN.has(run.status) || run.name !== 'predoc-pipeline') {
      return rejected('untrusted-run-history');
    }
    if (ACTIVE.has(run.status)) running = true;
    if (created > generated) newer = true;
  }
  if (!foundMain) return rejected('untrusted-run-history');
  if (running) return rejected('pipeline-already-running');
  if (newer) return rejected('newer-run-without-health-checkpoint');
  return {dispatch: true, reason: 'stale-without-newer-run'};
}

async function github(fetchImpl, token, path, {method = 'GET', body} = {}) {
  // No arbitrary hosts, paths, refs, or caller-controlled JSON are accepted.
  const options = {method, headers: {
    Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + token,
    'X-GitHub-Api-Version': '2022-11-28',
  }};
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetchImpl(API + path, options);
  } catch {
    // Never include thrown fetch errors: they can contain authorization data.
    throw new Error('External GitHub request failed');
  }
  if (response.status !== (method === 'POST' ? 204 : 200)) {
    // Never expose response body, request path, headers or authorization.
    throw new Error('External GitHub request failed');
  }
  if (method === 'POST') return null;
  try {
    return await response.json();
  } catch {
    throw new Error('External GitHub JSON invalid');
  }
}

function decodeHealth(file) {
  if (!file || file.type !== 'file' || file.path !== 'docs/data/health.json' ||
      file.encoding !== 'base64' || typeof file.content !== 'string' ||
      file.content.length > 512_000) {
    throw new Error('External health response invalid');
  }
  try {
    const bytes = Uint8Array.from(atob(file.content.replace(/\s/g, '')), c => c.charCodeAt(0));
    const health = JSON.parse(new TextDecoder().decode(bytes));
    if (!health || Array.isArray(health) || typeof health !== 'object') {
      throw new Error('not an object');
    }
    return health;
  } catch {
    throw new Error('External health response invalid');
  }
}

/** Side effect: dispatch exactly one main workflow iff BOTH safety gates pass. */
export async function checkAndRecover(env, {fetchImpl = fetch, nowMs = Date.now()} = {}) {
  if (env?.RECOVERY_ENABLED !== 'true') {
    return {...rejected('disabled'), action: 'none'};
  }
  if (typeof env.GITHUB_TOKEN !== 'string' || !env.GITHUB_TOKEN.trim()) {
    throw new Error('External ingestion observer not configured');
  }
  const token = env.GITHUB_TOKEN;
  const health = decodeHealth(await github(
    fetchImpl, token, '/contents/docs/data/health.json?ref=main'));
  const initial = decide(health, null, nowMs);
  if (initial.reason !== 'untrusted-run-history') {
    return {...initial, action: 'none'};
  }
  const response = await github(fetchImpl, token,
    '/actions/workflows/pipeline.yml/runs?branch=main&per_page=100');
  if (!response || !Array.isArray(response.workflow_runs) ||
      !Number.isSafeInteger(response.total_count) || response.total_count < 0 ||
      response.total_count < response.workflow_runs.length ||
      response.workflow_runs.length > 100) {
    throw new Error('External run history invalid');
  }
  const decision = decide(health, response.workflow_runs, nowMs);
  if (!decision.dispatch) return {...decision, action: 'none'};
  await github(fetchImpl, token, '/actions/workflows/pipeline.yml/dispatches',
    {method: 'POST', body: {ref: 'main', inputs: {dry_run: 'false'}}});
  return {...decision, action: 'requested'};
}

export default {
  // No HTTP path can be used to trigger ingestion or expose operator state.
  async fetch() {
    return new Response('Not found', {status: 404});
  },
  async scheduled(_controller, env) {
    try {
      const outcome = await checkAndRecover(env);
      console.log('External ingestion observer: ' + outcome.reason + '; action: ' + outcome.action);
    } catch {
      console.error('External ingestion observer failed closed');
      throw new Error('External ingestion observer failed closed');
    }
  },
};
