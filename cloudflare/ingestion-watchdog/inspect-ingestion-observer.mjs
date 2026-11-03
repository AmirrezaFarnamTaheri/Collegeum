/** Read-only Cloudflare inventory; never deploy, dispatch, or log API bodies. */
import {pathToFileURL} from 'node:url';

const NAME = 'collegeum-ingestion-observer';
const CRON = '37 */2 * * *';
const endpoint = 'https://api.cloudflare.com/client/v4/accounts/';

function empty(presence = 'access-unavailable') {
  return {
    worker: NAME, presence, cron: 'unverified',
    github_credential_binding: 'unverified',
    scheduled_handler: 'unverified', recovery_enabled: 'unverified',
  };
}

export async function inspectWorker({accountId, tokens, fetchImpl = fetch}) {
  if (!/^[a-f0-9]{32}$/.test(accountId || '') || !Array.isArray(tokens)) {
    return empty();
  }
  const credentials = [...new Set(tokens.filter(t => typeof t === 'string' && t.trim()))];
  if (!credentials.length) return empty();
  const base = endpoint + accountId + '/workers/scripts';

  async function read(token, suffix = '') {
    try {
      const response = await fetchImpl(base + suffix, {
        method: 'GET',
        headers: {Authorization: 'Bearer ' + token},
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) return null;
      const data = await response.json();
      if (data?.success !== true) return null;
      return data.result;
    } catch {
      // API response bodies, error objects, and credentials are never logged.
      return null;
    }
  }

  let listAccessible = false;
  for (const token of credentials) {
    const list = await read(token);
    if (!Array.isArray(list)) continue;
    listAccessible = true;
    const found = list.find(item => item && item.id === NAME);
    if (!found) continue;

    const schedules = await read(token, '/' + NAME + '/schedules');
    const secrets = await read(token, '/' + NAME + '/secrets');
    return {
      worker: NAME,
      presence: 'deployed',
      cron: Array.isArray(schedules?.schedules)
        ? schedules.schedules.some(entry => entry?.cron === CRON)
          ? 'configured' : 'missing'
        : 'unverified',
      github_credential_binding: Array.isArray(secrets)
        ? secrets.some(item => item?.name === 'GITHUB_TOKEN' && item?.type === 'secret_text')
          ? 'present' : 'missing'
        : 'unverified',
      scheduled_handler: Array.isArray(found.handlers)
        ? found.handlers.includes('scheduled') ? 'present' : 'missing'
        : 'unverified',
      // The scripts/schedules/secrets APIs do not certify the deployed var.
      recovery_enabled: 'unverified',
    };
  }
  return empty(listAccessible ? 'not-observed' : 'access-unavailable');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await inspectWorker({
    accountId: process.env.CLOUDFLARE_ACCOUNT_ID,
    tokens: [
      process.env.CF_TOKEN_PRIMARY,
      process.env.CF_TOKEN_SECONDARY,
      process.env.CF_TOKEN_TERTIARY,
    ],
  });
  console.log('Independent ingestion observer inventory: ' + JSON.stringify(result));
  if (result.presence !== 'deployed' || result.cron !== 'configured' ||
      result.github_credential_binding !== 'present' ||
      result.scheduled_handler !== 'present') {
    process.exitCode = 2;
  }
}
