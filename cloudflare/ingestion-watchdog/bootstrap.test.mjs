import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {preflightAbsent, verifyDisabledDeployment, auditAvailableAccounts} from './bootstrap-check.mjs';

const ACCOUNT = 'a'.repeat(32);
const TOKEN = 'test-sensitive-no-log';
const ROOT = 'https://api.cloudflare.com/client/v4/accounts/' + ACCOUNT + '/workers/scripts';
const NAME = 'collegeum-ingestion-observer';

function fake(routes) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.method, 'GET');
    assert.ok(url.startsWith(ROOT));
    assert.equal(options.headers.Authorization, 'Bearer ' + TOKEN);
    const value = routes[url];
    if (!value) return new Response('not found', {status: 404});
    if (typeof value === 'number') return new Response('denied', {status: value});
    return Response.json({success: true, result: value});
  };
  return {fetchImpl, calls};
}

test('only confirmed absence from list and direct settings allows disabled bootstrap', async () => {
  const {fetchImpl, calls} = fake({[ROOT]: [{id: 'collegeum-telegram'}]});
  const result = await preflightAbsent({accountId: ACCOUNT, token: TOKEN, fetchImpl});
  assert.deepEqual(result, {deploy: true, reason: 'confirmed-absent'});
  assert.equal(calls.length, 2);
  assert.ok(calls[1].url.endsWith('/' + NAME + '/settings'));
  assert.ok(!JSON.stringify(result).includes(TOKEN));
});

test('existing worker cannot be redeployed accidentally', async () => {
  const {fetchImpl, calls} = fake({[ROOT]: [{id: NAME, handlers: ['scheduled']}]});
  assert.deepEqual(await preflightAbsent({accountId: ACCOUNT, token: TOKEN, fetchImpl}),
    {deploy: false, reason: 'already-deployed'});
  assert.equal(calls.length, 1);
});

test('insufficient permissions, malformed settings or missing credentials fail closed', async () => {
  const denied = fake({[ROOT]: 403});
  assert.equal((await preflightAbsent({accountId: ACCOUNT, token: TOKEN,
    fetchImpl: denied.fetchImpl})).deploy, false);
  const present = fake({[ROOT]: [], [ROOT + '/' + NAME + '/settings']: {bindings: []}});
  assert.deepEqual(await preflightAbsent({accountId: ACCOUNT, token: TOKEN,
    fetchImpl: present.fetchImpl}), {deploy: false, reason: 'existing-settings'});
  const missing = fake({});
  assert.equal((await preflightAbsent({accountId: 'bad', token: TOKEN,
    fetchImpl: missing.fetchImpl})).deploy, false);
  assert.equal(missing.calls.length, 0);
});

test('post-deploy verifier requires deployed worker, correct cron and explicit disabled variable', async () => {
  const routes = {
    [ROOT]: [{id: NAME, handlers: ['scheduled']}],
    [ROOT + '/' + NAME + '/schedules']: {schedules: [{cron: '37 */2 * * *'}]},
    [ROOT + '/' + NAME + '/settings']: {bindings: [
      {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'false'},
    ]},
  };
  const {fetchImpl} = fake(routes);
  const found = await verifyDisabledDeployment({accountId: ACCOUNT, token: TOKEN, fetchImpl});
  assert.deepEqual(found, {verified: true, reason: 'deployed-disabled'});
  const changed = fake({...routes, [ROOT + '/' + NAME + '/settings']: {bindings: [
    {name: 'RECOVERY_ENABLED', type: 'plain_text', text: 'true'},
  ]}});
  assert.equal((await verifyDisabledDeployment({accountId: ACCOUNT, token: TOKEN,
    fetchImpl: changed.fetchImpl})).verified, false);
});

test('one-time disabled bootstrap workflow uses trusted main and no Github credential injection', () => {
  const yml = readFileSync(new URL('../../.github/workflows/bootstrap-ingestion-observer-disabled.yml',
    import.meta.url), 'utf8');
  assert.match(yml, /refs\/heads\/main/);
  assert.match(yml, /--dry-run/);
  assert.match(yml, /RECOVERY_ENABLED:false/);
  assert.doesNotMatch(yml, /GITHUB_TOKEN:|wrangler secret put|RECOVERY_ENABLED:true/);
});

test('worker-specific settings denial cannot authorize even a disabled deployment', async () => {
  const {fetchImpl, calls} = fake({
    [ROOT]: [{id: 'collegeum-telegram'}],
    [ROOT + '/' + NAME + '/settings']: 403,
  });
  const result = await preflightAbsent({accountId: ACCOUNT, token: TOKEN, fetchImpl});
  assert.deepEqual(result, {deploy: false, reason: 'absence-unverified'});
  assert.equal(calls.length, 2);
});

const ACCOUNT_B = 'b'.repeat(32);
const ACCOUNT_URL = 'https://api.cloudflare.com/client/v4/accounts?per_page=50';
const inventoryResult = (result, total_pages = 1) =>
  ({success: true, result, result_info: {total_pages}});

function auditMock(routes) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    assert.equal(options.method, 'GET');
    assert.ok(options.headers.Authorization.startsWith('Bearer '));
    const entry = routes[url];
    if (typeof entry === 'number') return new Response('', {status: entry});
    if (!entry) return new Response('', {status: 404});
    return Response.json(entry);
  };
  return {fetchImpl, calls};
}

test('cross-account audit blocks a named observer found outside the target account', async () => {
  const second = 'other-inventory-token';
  const mock = auditMock({
    [ACCOUNT_URL]: inventoryResult([{id: ACCOUNT}, {id: ACCOUNT_B}]),
    [ROOT]: inventoryResult([{id: 'collegeum-telegram'}]),
    ['https://api.cloudflare.com/client/v4/accounts/' + ACCOUNT_B +
      '/workers/scripts']: inventoryResult([{id: NAME}]),
  });
  const outcome = await auditAvailableAccounts({
    targetAccountId: ACCOUNT, tokens: [TOKEN, second], fetchImpl: mock.fetchImpl,
  });
  assert.deepEqual(outcome, {safe: false, reason: 'duplicate-in-accessible-account'});
  assert.ok(mock.calls.every(call => call.options.method === 'GET'));
  assert.doesNotMatch(JSON.stringify(outcome), /other-inventory-token|test-sensitive-no-log/);
});

test('cross-account audit allows one exhaustive clean accessible inventory', async () => {
  const mock = auditMock({
    [ACCOUNT_URL]: inventoryResult([{id: ACCOUNT}, {id: ACCOUNT_B}]),
    [ROOT]: inventoryResult([{id: 'collegeum-telegram'}]),
    ['https://api.cloudflare.com/client/v4/accounts/' + ACCOUNT_B +
      '/workers/scripts']: inventoryResult([]),
  });
  assert.deepEqual(await auditAvailableAccounts({
    targetAccountId: ACCOUNT, tokens: [TOKEN], fetchImpl: mock.fetchImpl,
  }), {safe: true, reason: 'accessible-accounts-checked'});
  assert.equal(mock.calls.length, 3);
});

test('cross-account audit fails closed for missing target, denied access or pagination', async () => {
  for (const routes of [
    {[ACCOUNT_URL]: 403},
    {[ACCOUNT_URL]: inventoryResult([{id: ACCOUNT}], 2)},
    {[ACCOUNT_URL]: inventoryResult([{id: ACCOUNT_B}])},
    {[ACCOUNT_URL]: inventoryResult([{id: ACCOUNT}]), [ROOT]: 403},
  ]) {
    const mock = auditMock(routes);
    const out = await auditAvailableAccounts({
      targetAccountId: ACCOUNT, tokens: [TOKEN], fetchImpl: mock.fetchImpl,
    });
    assert.equal(out.safe, false, out.reason);
  }
});

test('bootstrap workflow requires cross-account check before running any deploy', () => {
  const yml = readFileSync(new URL('../../.github/workflows/bootstrap-ingestion-observer-disabled.yml',
    import.meta.url), 'utf8');
  const audit = yml.indexOf('bootstrap-check.mjs inventory');
  const deploy = yml.indexOf('wrangler deploy --config');
  assert.ok(audit >= 0 && deploy > audit);
  // Deployment was successfully bootstrapped once on 2026-11-03.
  // Future code changes must NOT schedule automatic overwrite attempts.
  assert.match(yml, /workflow_dispatch/);
  assert.doesNotMatch(yml, /\n  push:/);
});
