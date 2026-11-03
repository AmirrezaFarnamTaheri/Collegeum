import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import worker, {decide, checkAndRecover} from './worker.mjs';

const NOW = Date.parse('2026-11-03T14:30:00Z');
const OLD = '2026-11-03T02:21:23Z';
const HEALTH = {generated_at: OLD, last_run: {run_id: '41564513678', outcome: 'ok'}};
const RUN = {created_at: '2026-11-03T02:11:05Z', status: 'completed',
  head_branch: 'main', name: 'predoc-pipeline', conclusion: 'success'};
const TOKEN = 'gh_token_test_sensitive_123';
const ENV = {RECOVERY_ENABLED: 'true', GITHUB_TOKEN: TOKEN};
const repo = 'https://api.github.com/repos/AmirrezaFarnamTaheri/Collegeum';

function mockFetch({health = HEALTH, runs = [RUN], healthStatus = 200,
                    runsStatus = 200, dispatchStatus = 204} = {}) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    if (url === repo + '/contents/docs/data/health.json?ref=main') {
      if (healthStatus !== 200) return new Response('', {status: healthStatus});
      return Response.json({type: 'file', path: 'docs/data/health.json', encoding: 'base64',
        content: btoa(JSON.stringify(health))});
    }
    if (url === repo + '/actions/workflows/pipeline.yml/runs?branch=main&per_page=100') {
      if (runsStatus !== 200) return new Response('', {status: runsStatus});
      return Response.json({total_count: runs.length, workflow_runs: runs});
    }
    if (url === repo + '/actions/workflows/pipeline.yml/dispatches') {
      return new Response(null, {status: dispatchStatus});
    }
    assert.fail('Unexpected URL: ' + url);
  };
  return {fetchImpl, calls};
}

test('stale snapshot with only older completed ingestion dispatches one guarded main run', async () => {
  const {fetchImpl, calls} = mockFetch();
  const result = await checkAndRecover(ENV, {fetchImpl, nowMs: NOW});
  assert.deepEqual(result, {dispatch: true, reason: 'stale-without-newer-run', action: 'requested'});
  assert.equal(calls.length, 3);
  assert.equal(calls[2].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[2].options.body), {ref: 'main', inputs: {dry_run: 'false'}});
  for (const call of calls) {
    assert.equal(call.options.headers.Authorization, 'Bearer ' + TOKEN);
    assert.ok(call.url.startsWith(repo));
  }
});

test('a fresh health checkpoint does not even query Actions or dispatch', async () => {
  const {fetchImpl, calls} = mockFetch({health: {generated_at: '2026-11-03T13:59:00Z'}});
  assert.deepEqual(await checkAndRecover(ENV, {fetchImpl, nowMs: NOW}),
    {dispatch: false, reason: 'fresh', action: 'none'});
  assert.equal(calls.length, 1);
});

test('queued or in-progress pipeline prevents duplicate dispatch', async () => {
  for (const status of ['queued', 'requested', 'waiting', 'pending', 'in_progress']) {
    const {fetchImpl, calls} = mockFetch({runs: [{...RUN, status}]});
    const result = await checkAndRecover(ENV, {fetchImpl, nowMs: NOW});
    assert.equal(result.reason, 'pipeline-already-running', status);
    assert.equal(result.dispatch, false);
    assert.equal(calls.length, 2);
  }
});

test('newer failed or successful pipeline with no published checkpoint is not retried', async () => {
  for (const conclusion of ['failure', 'success', 'cancelled']) {
    const {fetchImpl, calls} = mockFetch({runs: [
      {...RUN, created_at: '2026-11-03T09:00:00Z', conclusion}, RUN]});
    const result = await checkAndRecover(ENV, {fetchImpl, nowMs: NOW});
    assert.equal(result.reason, 'newer-run-without-health-checkpoint');
    assert.equal(calls.length, 2);
  }
});

test('missing, naive, future and malformed health timestamps fail closed', async () => {
  for (const generated_at of [null, '', '2026-11-03', 'not-a-time',
                             '2026-11-03T14:35:00Z']) {
    const {fetchImpl, calls} = mockFetch({health: {generated_at}});
    const result = await checkAndRecover(ENV, {fetchImpl, nowMs: NOW});
    assert.equal(result.dispatch, false, String(generated_at));
    assert.equal(calls.length, 1);
  }
});

test('empty, malformed or future Actions histories fail closed', async () => {
  for (const runs of [[], [null], [{...RUN, status: 'weird'}],
                      [{...RUN, created_at: 'not-a-time'}],
                      [{...RUN, created_at: '2026-11-03T14:40:00Z'}]]) {
    const {fetchImpl, calls} = mockFetch({runs});
    const result = await checkAndRecover(ENV, {fetchImpl, nowMs: NOW});
    assert.equal(result.dispatch, false);
    assert.equal(result.reason, 'untrusted-run-history');
    assert.equal(calls.length, 2);
  }
});

test('API failures cannot dispatch and errors never include response bodies or tokens', async () => {
  for (const selection of [{healthStatus: 403}, {runsStatus: 502}]) {
    const {fetchImpl, calls} = mockFetch(selection);
    await assert.rejects(checkAndRecover(ENV, {fetchImpl, nowMs: NOW}),
      error => !String(error).includes(TOKEN));
    assert.ok(calls.length < 3);
  }
});

test('ambiguous dispatch failure does not retry POST', async () => {
  const {fetchImpl, calls} = mockFetch({dispatchStatus: 409});
  await assert.rejects(checkAndRecover(ENV, {fetchImpl, nowMs: NOW}),
    /External GitHub request failed/);
  assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
});

test('opt-in is disabled by default and missing secret fails without network', async () => {
  const {fetchImpl, calls} = mockFetch();
  assert.deepEqual(await checkAndRecover({RECOVERY_ENABLED: 'false'}, {fetchImpl, nowMs: NOW}),
    {dispatch: false, reason: 'disabled', action: 'none'});
  await assert.rejects(checkAndRecover({RECOVERY_ENABLED: 'true'}, {fetchImpl, nowMs: NOW}),
    /not configured/);
  assert.equal(calls.length, 0);
});

test('public HTTP entrypoint never triggers recovery', async () => {
  const response = await worker.fetch(new Request('https://observer.example/trigger'), ENV);
  assert.equal(response.status, 404);
  assert.equal((await response.text()).includes(TOKEN), false);
});

test('decision gate separately fails closed for trust and clock anomalies', () => {
  assert.equal(decide(HEALTH, [RUN], NOW).dispatch, true);
  assert.equal(decide({generated_at: '2026-11-03T14:00:00Z'}, [RUN], NOW).reason, 'fresh');
  assert.equal(decide(HEALTH, [{...RUN, head_branch: 'other'}], NOW).reason,
    'untrusted-run-history');
  assert.equal(decide(HEALTH, [RUN, {...RUN, status: 'in_progress'}], NOW).reason,
    'pipeline-already-running');
});

test('Cloudflare cron is independent and remains opt-in until credential activation', () => {
  const config = readFileSync(new URL('./wrangler.jsonc', import.meta.url), 'utf8');
  assert.match(config, /"workers_dev": false/);
  assert.match(config, /"crons": \["37 \*\/2 \* \* \*"\]/);
  assert.match(config, /"RECOVERY_ENABLED": "false"/);
  assert.doesNotMatch(config, /GITHUB_TOKEN/);
});
