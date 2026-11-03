/** Minimal read-only preflight and post-deploy check for disabled observer bootstrap.
 * No write API calls, GitHub credentials, response-body logs, or automatic retry.
 */
import {pathToFileURL} from 'node:url';

const NAME = 'collegeum-ingestion-observer';
const CRON = '37 */2 * * *';
const ROOT = 'https://api.cloudflare.com/client/v4/accounts/';

function status(deploy, reason) { return {deploy, reason}; }

async function request(fetchImpl, token, url) {
  try {
    const response = await fetchImpl(url, {
      method: 'GET',
      headers: {Authorization: 'Bearer ' + token},
      signal: AbortSignal.timeout(15000),
    });
    if (response.status === 404) return {status: 404, result: null};
    if (!response.ok) return {status: response.status, result: null};
    const json = await response.json();
    if (json?.success !== true) return {status: 0, result: null};
    return {status: 200, result: json.result};
  } catch {
    return {status: 0, result: null};
  }
}

function scoped(accountId, token) {
  return /^[a-f0-9]{32}$/.test(accountId || '') &&
    typeof token === 'string' && token.trim().length > 0;
}

/** Fail closed unless every currently available credential's account inventory is
 * accessible and no account shows the observer name. This does not claim
 * visibility into accounts outside the available credentials.
 */
export async function auditAvailableAccounts({
  targetAccountId, tokens, fetchImpl = fetch,
}) {
  const rejected = reason => ({safe: false, reason});
  if (!/^[a-f0-9]{32}$/.test(targetAccountId || '') || !Array.isArray(tokens)) {
    return rejected('account-inventory-unconfigured');
  }
  const credentials = [...new Set(tokens.filter(
    value => typeof value === 'string' && value.trim(),
  ))];
  if (credentials.length === 0 || credentials.length > 4) {
    return rejected('account-inventory-unconfigured');
  }
  async function read(token, url) {
    try {
      const response = await fetchImpl(url, {
        method: 'GET', headers: {Authorization: 'Bearer ' + token},
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) return null;
      const parsed = await response.json();
      return parsed?.success === true ? parsed : null;
    } catch {
      return null;
    }
  }
  let targetObserved = false;
  for (const token of credentials) {
    const accounts = await read(token, ROOT.slice(0, -1) + '?per_page=50');
    if (!accounts || !Array.isArray(accounts.result) ||
        accounts.result.length >= 50 ||
        (accounts.result_info && (
          !Number.isSafeInteger(accounts.result_info.total_pages) ||
          accounts.result_info.total_pages !== 1))) {
      return rejected('account-inventory-unavailable');
    }
    for (const account of accounts.result) {
      if (!account || !/^[a-f0-9]{32}$/.test(account.id || '')) {
        return rejected('account-inventory-unavailable');
      }
      if (account.id === targetAccountId) targetObserved = true;
      const scripts = await read(token, ROOT + account.id + '/workers/scripts');
      if (!scripts || !Array.isArray(scripts.result) ||
          scripts.result.length >= 100 ||
          (scripts.result_info && (
            !Number.isSafeInteger(scripts.result_info.total_pages) ||
            scripts.result_info.total_pages !== 1))) {
        return rejected('account-script-inventory-unavailable');
      }
      if (scripts.result.some(worker => worker?.id === NAME)) {
        return rejected('duplicate-in-accessible-account');
      }
    }
  }
  if (!targetObserved) return rejected('target-account-not-enumerated');
  return {safe: true, reason: 'accessible-accounts-checked'};
}

export async function preflightAbsent({accountId, token, fetchImpl = fetch}) {
  if (!scoped(accountId, token)) return status(false, 'unconfigured');
  const base = ROOT + accountId + '/workers/scripts';
  const list = await request(fetchImpl, token, base);
  if (list.status !== 200 || !Array.isArray(list.result)) {
    return status(false, 'account-inventory-unavailable');
  }
  if (list.result.some(worker => worker?.id === NAME)) {
    return status(false, 'already-deployed');
  }
  // Require direct evidence as well; listing-only absence is not sufficient.
  const settings = await request(fetchImpl, token, base + '/' + NAME + '/settings');
  if (settings.status === 404) return status(true, 'confirmed-absent');
  if (settings.status === 200) return status(false, 'existing-settings');
  return status(false, 'absence-unverified');
}

export async function verifyDisabledDeployment({accountId, token, fetchImpl = fetch}) {
  const failure = reason => ({verified: false, reason});
  if (!scoped(accountId, token)) return failure('unconfigured');
  const base = ROOT + accountId + '/workers/scripts';
  const list = await request(fetchImpl, token, base);
  const found = list.result?.find?.(worker => worker?.id === NAME);
  if (list.status !== 200 || !Array.isArray(list.result) ||
      !Array.isArray(found?.handlers) || !found.handlers.includes('scheduled')) {
    return failure('worker-identity-or-handler-unverified');
  }
  const cron = await request(fetchImpl, token, base + '/' + NAME + '/schedules');
  if (cron.status !== 200 || !Array.isArray(cron.result?.schedules) ||
      !cron.result.schedules.some(entry => entry?.cron === CRON)) {
    return failure('cron-unverified');
  }
  const settings = await request(fetchImpl, token, base + '/' + NAME + '/settings');
  if (settings.status !== 200 || !Array.isArray(settings.result?.bindings) ||
      !settings.result.bindings.some(binding =>
        binding?.name === 'RECOVERY_ENABLED' &&
        binding?.type === 'plain_text' && binding?.text === 'false')) {
    return failure('disabled-binding-unverified');
  }
  return {verified: true, reason: 'deployed-disabled'};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = {
    accountId: process.env.CLOUDFLARE_ACCOUNT_ID,
    token: process.env.CLOUDFLARE_API_TOKEN,
  };
  const mode = process.argv[2];
  if (mode === 'inventory') {
    const result = await auditAvailableAccounts({
      targetAccountId: process.env.CLOUDFLARE_ACCOUNT_ID,
      tokens: [
        process.env.CLOUDFLARE_API_TOKEN,
        process.env.CF_TOKEN_PRIMARY,
        process.env.CF_TOKEN_SECONDARY,
        process.env.CF_TOKEN_TERTIARY,
      ],
    });
    console.log('Cloudflare cross-account preflight: ' + result.reason);
    if (!result.safe) process.exitCode = 2;
  } else if (mode === 'preflight') {
    const result = await preflightAbsent(args);
    console.log('Cloudflare disabled bootstrap preflight: ' + result.reason);
    if (!result.deploy) process.exitCode = 2;
  } else if (mode === 'verify') {
    const result = await verifyDisabledDeployment(args);
    console.log('Cloudflare disabled bootstrap postcheck: ' + result.reason);
    if (!result.verified) process.exitCode = 2;
  } else {
    console.error('Unknown disabled bootstrap inspection mode');
    process.exitCode = 2;
  }
}
