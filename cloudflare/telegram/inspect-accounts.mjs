/** Read-only discovery. Never log response bodies or credential values. */
const labels = ['CF_TOKEN_PRIMARY', 'CF_TOKEN_SECONDARY', 'CF_TOKEN_TERTIARY'];
let found = false;
for (const label of labels) {
  const token = process.env[label];
  if (!token) continue;
  try {
    const response = await fetch('https://api.cloudflare.com/client/v4/accounts?per_page=50', {
      headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(15000),
    });
    const data = await response.json();
    if (!response.ok || !data.success || !Array.isArray(data.result)) {
      console.log(`${label}: account discovery unavailable (HTTP ${response.status})`);
      continue;
    }
    for (const account of data.result) {
      if (!/^[a-f0-9]{32}$/.test(account.id)) continue;
      const workers = await fetch(`https://api.cloudflare.com/client/v4/accounts/${account.id}/workers/scripts`, {
        headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(15000),
      });
      const scripts = await workers.json();
      const accessible = workers.ok && scripts.success && Array.isArray(scripts.result);
      const metadata = {};
      for (const [field, path] of [
        ['subdomain', `accounts/${account.id}/workers/subdomain`],
        ['zones', `zones?account.id=${account.id}&per_page=50`],
      ]) {
        const extra = await fetch(`https://api.cloudflare.com/client/v4/${path}`, {
          headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(15000),
        });
        const info = await extra.json();
        metadata[field] = extra.ok && info.success
          ? field === 'zones' ? info.result.map(z => z.name) : info.result.subdomain
          : 'not accessible with this token';
      }
      console.log(JSON.stringify({credential: label, account_id: account.id,
        worker_access: accessible, existing_bot: accessible && scripts.result.some(s => s.id === 'collegeum-telegram'),
        ...metadata}));
      found ||= accessible;
    }
  } catch {
    console.log(`${label}: discovery request failed`);
  }
}
if (!found) process.exitCode = 1;
