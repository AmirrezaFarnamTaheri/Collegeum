import test from 'node:test';
import assert from 'node:assert/strict';
import { selectToken, verifyTargetToken } from './deploy-token.mjs';

test('deployment runs rotate among configured tokens without exposing them', async () => {
  assert.equal(await selectToken(['a', 'b', 'c'], 0, async () => true), 'a');
  assert.equal(await selectToken(['a', 'b', 'c'], 1, async () => true), 'b');
  assert.equal(await selectToken(['a', 'b', 'c'], 2, async () => true), 'c');
});
test('invalid and unavailable tokens fall back before deployment', async () => {
  const attempts = [];
  const token = await selectToken(['a', 'b', 'c'], 0, async item => {
    attempts.push(item);
    if (item === 'a') throw new Error('network error');
    return item === 'c';
  });
  assert.equal(token, 'c');
  assert.deepEqual(attempts, ['a', 'b', 'c']);
});
test('empty or wholly invalid credentials fail closed', async () => {
  await assert.rejects(selectToken([], 0, async () => true), /No Cloudflare/);
  await assert.rejects(selectToken(['a', '', 'a'], 0, async () => false), /passed verification/);
});

test('active token without target Worker account access is rejected', async () => {
  const urls = [];
  const verified = await verifyTargetToken('mock', 'a'.repeat(32), async url => {
    urls.push(url);
    return url.endsWith('/verify')
      ? Response.json({ success: true, result: { status: 'active' } })
      : Response.json({ success: false }, { status: 403 });
  });
  assert.equal(verified, false);
  assert.equal(urls.length, 2);
  assert.ok(urls[1].includes(`/accounts/${'a'.repeat(32)}/workers/scripts`));
  await assert.rejects(verifyTargetToken('mock', ''), /ACCOUNT_ID/);
});
