import assert from 'node:assert/strict';
import test from 'node:test';
import {inspectWorker} from './inspect-ingestion-observer.mjs';

const ACCOUNT = 'c'.repeat(32);
const BASE = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT}/workers/scripts`;
const NAME = 'collegeum-ingestion-observer';
const TOKEN = 'test-token-never-disclose';
const SCHEDULES = BASE + '/' + NAME + '/schedules';
const SETTINGS = BASE + '/' + NAME + '/settings';
const SECRETS = BASE + '/' + NAME + '/secrets';

function client({status = 200, settings = {bindings: [
  {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'false'},
  {name: 'OTHER_SECRET', type: 'secret_text', text: 'sensitive-do-not-disclose'},
]}} = {}) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.method, 'GET');
    assert.equal(options.headers.Authorization, 'Bearer ' + TOKEN);
    if (url === BASE) return Response.json({success: true,
      result: [{id: NAME, handlers: ['scheduled']}]});
    if (url === SCHEDULES) return Response.json({success: true,
      result: {schedules: [{cron: '37 */2 * * *'}]}});
    if (url === SECRETS) return Response.json({success: true,
      result: [{name: 'ANOTHER_SECRET', type: 'secret_text'}]});
    if (url === SETTINGS) {
      if (status !== 200) return new Response(null, {status});
      return Response.json({success: true, result: settings});
    }
    throw new Error('Unexpected URL: ' + url);
  };
  return {calls, fetchImpl};
}

test('live disabled binding is independently identified without exposing settings contents', async () => {
  const {calls, fetchImpl} = client();
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
  assert.equal(result.presence, 'deployed');
  assert.equal(result.cron, 'configured');
  assert.equal(result.github_credential_binding, 'missing');
  assert.equal(result.recovery_enabled, 'disabled');
  assert.ok(calls.some(x => x.url === SETTINGS));
  assert.equal(calls.length, 4);
  assert.doesNotMatch(JSON.stringify(result), /sensitive-do-not-disclose|test-token-never-disclose/);
});

test('enabled binding is recognized without implying successful ingestion recovery', async () => {
  const {fetchImpl} = client({settings: {bindings: [
    {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'true'},
  ]}});
  const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
  assert.equal(result.recovery_enabled, 'enabled');
  assert.equal(result.github_credential_binding, 'missing');
});

test('API denial and ambiguous or duplicate bindings remain unverified', async () => {
  for (const settings of [
    null,
    {bindings: []},
    {bindings: [{name: 'RECOVERY_ENABLED', type: 'secret_text'}]},
    {bindings: [{name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'TRUE'}]},
    {bindings: [
      {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'true'},
      {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'false'},
    ]},
  ]) {
    const {fetchImpl} = client({settings});
    const result = await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl});
    assert.equal(result.recovery_enabled, 'unverified');
  }
  const {fetchImpl} = client({status: 403});
  assert.equal((await inspectWorker({accountId: ACCOUNT, tokens: [TOKEN], fetchImpl}))
    .recovery_enabled, 'unverified');
});
