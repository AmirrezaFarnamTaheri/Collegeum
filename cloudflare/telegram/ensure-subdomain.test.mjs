import assert from 'node:assert/strict';
import test from 'node:test';
import {ensureSubdomain} from './ensure-subdomain.mjs';

test('existing subdomain is preserved and never renamed', async () => {
  const calls = [];
  const name = await ensureSubdomain('a'.repeat(32), 'secret', 'new-name', async (url, options) => {
    calls.push(options);
    return Response.json({success: true, result: {subdomain: 'existing'}});
  });
  assert.equal(name, 'existing');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, undefined);
});

test('missing subdomain is registered, but permission failures never trigger writes', async () => {
  for (const code of [10007, 10000]) {
    const calls = [];
    const request = async (_url, options) => {
      calls.push(options);
      if (options.method === 'PUT') return Response.json({success: true, result: {subdomain: 'new-name'}});
      return Response.json({success: false, errors: [{code}]}, {status: 400});
    };
    if (code === 10007) {
      assert.equal(await ensureSubdomain('a'.repeat(32), 'secret', 'new-name', request), 'new-name');
      assert.deepEqual(JSON.parse(calls[1].body), {subdomain: 'new-name'});
    } else {
      await assert.rejects(ensureSubdomain('a'.repeat(32), 'secret', 'new-name', request));
      assert.equal(calls.length, 1);
    }
  }
});
