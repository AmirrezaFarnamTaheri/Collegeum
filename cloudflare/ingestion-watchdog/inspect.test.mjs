import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {inspectWorker} from './inspect-ingestion-observer.mjs';

const ACCOUNT = '0'.repeat(32);
const BASE = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT}/workers/scripts`;
const TOKEN = 'sensitive-token-do-not-log';
const NAME = 'collegeum-ingestion-observer';

function api(responses) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.method, 'GET');
    assert.ok(url.startsWith(BASE));
    const entry = responses[url];
    if (entry === undefined) return new Response('', {status: 404});
    if (Number.isInteger(entry)) return new Response('', {status: entry});
    return Response.json({success: true, result: entry});
  };
  return {fetchImpl, calls};
}

test('existing worker identity, Cron and secret name are detected without leaking values', async () => {
  const {fetchImpl, calls} = api({
    [BASE]: [{id: NAME, handlers: ['fetch', 'scheduled']}],
    [BASE + '/' + NAME + '/schedules']: {schedules: [{cron: '37 */2 * * *'}]},
    [BASE + '/' + NAME + '/secrets']: [
      {name: 'GITHUB_TOKEN', type: 'secret_text', text: 'never-log-secret-value'},
      {name: 'OTHER', type: 'secret_text'},
    ],
  });
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
  assert.deepEqual(result, {
    worker: NAME, presence: 'deployed', cron: 'configured',
    github_credential_binding: 'present', scheduled_handler: 'present',
    recovery_enabled: 'unverified',
  });
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.options.headers.Authorization === 'Bearer ' + TOKEN));
  assert.ok(!JSON.stringify(result).includes(TOKEN));
  assert.ok(!JSON.stringify(result).includes('never-log-secret-value'));
});

test('no observed Worker is not definitive absence; never creates a script', async () => {
  const {fetchImpl, calls} = api({
    [BASE]: [{id: 'collegeum-telegram'}],
  });
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
  assert.equal(result.presence, 'not-observed');
  assert.equal(result.cron, 'unverified');
  assert.equal(result.github_credential_binding, 'unverified');
  assert.equal(calls.length, 1);
});

test('403, missing account or credential, malformed responses fail closed', async () => {
  const denied = api({[BASE]: 403});
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl: denied.fetchImpl});
  assert.equal(result.presence, 'access-unavailable');
  assert.equal(result.cron, 'unverified');
  const noToken = api({});
  assert.equal((await inspectWorker({accountId: ACCOUNT, tokens: [], fetchImpl: noToken.fetchImpl})).presence, 'access-unavailable');
  assert.equal((await inspectWorker({accountId: 'invalid', tokens: [TOKEN], fetchImpl: noToken.fetchImpl})).presence, 'access-unavailable');
  assert.equal(noToken.calls.length, 0);
});

test('incomplete permission does not make Cron or secret look healthy', async () => {
  const {fetchImpl} = api({
    [BASE]: [{id: NAME}],
    [BASE + '/' + NAME + '/schedules']: 403,
    [BASE + '/' + NAME + '/secrets']: 403,
  });
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
  assert.equal(result.presence, 'deployed');
  assert.equal(result.cron, 'unverified');
  assert.equal(result.github_credential_binding, 'unverified');
  assert.equal(result.scheduled_handler, 'unverified');
});

test('Cloudflare audit workflow remains main-only and inspection-only', () => {
  const yaml = readFileSync(new URL('../../.github/workflows/inspect-ingestion-observer.yml', import.meta.url), 'utf8');
  assert.match(yaml, /refs\/heads\/main/);
  assert.match(yaml, /inspect-ingestion-observer\.mjs/);
  assert.doesNotMatch(yaml, /wrangler deploy|wrangler secret put|workflow_dispatch.*dry_run|curl.*-X POST/i);
});
