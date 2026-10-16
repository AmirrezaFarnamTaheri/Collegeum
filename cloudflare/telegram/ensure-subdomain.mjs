/** Register a workers.dev hostname only for an account with no existing one. */
import {pathToFileURL} from 'node:url';

export async function ensureSubdomain(account, token, name, request = fetch) {
  if (!/^[a-f0-9]{32}$/.test(account || '') || !token ||
      !/^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$/.test(name || ''))
    throw new Error('Invalid account or Worker subdomain configuration');
  const url = `https://api.cloudflare.com/client/v4/accounts/${account}/workers/subdomain`;
  const headers = {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'};
  const existing = await request(url, {headers, signal: AbortSignal.timeout(15000)});
  const current = await existing.json();
  if (existing.ok && current.success && typeof current.result?.subdomain === 'string')
    return current.result.subdomain;
  if (!current.errors?.some(error => error.code === 10007))
    throw new Error(`Cannot inspect Worker subdomain (HTTP ${existing.status})`);
  const created = await request(url, {method: 'PUT', headers,
    body: JSON.stringify({subdomain: name}), signal: AbortSignal.timeout(15000)});
  const result = await created.json();
  if (!created.ok || !result.success || result.result?.subdomain !== name)
    throw new Error(`Cannot register Worker subdomain (HTTP ${created.status})`);
  return name;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const account = process.env.CLOUDFLARE_ACCOUNT_ID;
  ensureSubdomain(account, process.env.CLOUDFLARE_API_TOKEN,
    process.env.CLOUDFLARE_WORKERS_SUBDOMAIN || `collegeum-${account?.slice(0, 8)}`)
    .then(name => console.log(`Worker URL: https://collegeum-telegram.${name}.workers.dev`))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
