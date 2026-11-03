import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {preflightAbsent, verifyDisabledDeployment} from './bootstrap-check.mjs';

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
