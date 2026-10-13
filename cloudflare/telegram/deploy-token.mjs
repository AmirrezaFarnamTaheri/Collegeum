import { appendFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export async function selectToken(tokens, runNumber, verify) {
  const available = [...new Set(tokens.filter(token => typeof token === 'string' && token.trim()))];
  if (!available.length) throw new Error('No Cloudflare deployment token configured');
  const start = (Number(runNumber) || 0) % available.length;
  for (let index = 0; index < available.length; index++) {
    const token = available[(start + index) % available.length];
    try {
      if (await verify(token)) return token;
    } catch { /* Try another token before any deployment starts. */ }
  }
  throw new Error('No configured Cloudflare deployment token passed verification');
}

export async function verifyTargetToken(token, accountId, request = fetch) {
  if (!/^[a-f0-9]{32}$/.test(accountId || '')) {
    throw new Error('Set the intended CLOUDFLARE_ACCOUNT_ID first');
  }
  let active = false;
  for (const url of [
    'https://api.cloudflare.com/client/v4/user/tokens/verify',
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/tokens/verify`,
  ]) {
    const response = await request(url, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) continue;
    const body = await response.json();
    if (body.success === true && body.result?.status === 'active') {
      active = true;
      break;
    }
  }
  if (!active) return false;
  const response = await request(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/scripts`, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(10000),
    });
  return response.ok && (await response.json()).success === true;
}

async function main() {
  const chosen = await selectToken([
    process.env.CF_TOKEN_PRIMARY, process.env.CF_TOKEN_SECONDARY, process.env.CF_TOKEN_TERTIARY,
  ], process.env.GITHUB_RUN_NUMBER,
  token => verifyTargetToken(token, process.env.CLOUDFLARE_ACCOUNT_ID));
  if (!process.env.GITHUB_ENV || /[\r\n]/.test(chosen)) {
    throw new Error('Invalid deployment environment');
  }
  appendFileSync(process.env.GITHUB_ENV, `CLOUDFLARE_API_TOKEN=${chosen}\n`);
  console.log('Cloudflare deployment token verified; credential value withheld');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { console.error('Cloudflare token selection failed'); process.exitCode = 1; });
}
