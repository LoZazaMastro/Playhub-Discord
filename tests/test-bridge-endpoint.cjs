const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync('defaults/steamcord_client.js', 'utf8');
const helper = source.slice(0, source.indexOf('// Detect host:'));
function fixture(host, port) {
  const window = { STEAMCORD_HOST: host };
  if (port !== undefined) window.STEAMCORD_BRIDGE_PORT = port;
  vm.runInNewContext(helper, {window});
  return window;
}
test('Windows uses the negotiated endpoint for HTTP and websocket', () => {
  const w = fixture('windows', 55001);
  assert.equal(w.__sc_bridgeUrl('/openkb'), 'http://127.0.0.1:55001/openkb');
  assert.equal(w.__sc_bridgeUrl('/socket?bridge=', true), 'ws://127.0.0.1:55001/socket?bridge=');
  w.STEAMCORD_BRIDGE_PORT = 55002;
  assert.equal(w.__sc_bridgeUrl('/socket', true), 'ws://127.0.0.1:55002/socket');
});
test('Windows cannot silently reconnect to a fixed or malformed endpoint', () => {
  for (const port of [undefined, null, 0, -1, 65536, true, '55001', 1.2])
    assert.throws(() => fixture('windows', port).__sc_bridgeUrl('/socket', true));
  for (const path of ['//foreign.invalid/socket', 'https://foreign.invalid/', null])
    assert.throws(() => fixture('windows', 55001).__sc_bridgeUrl(path));
});
test('Linux retains the original port when bootstrap is absent', () => {
  assert.equal(fixture('linux').__sc_bridgeUrl('/socket', true), 'ws://127.0.0.1:65123/socket');
});
test('all injected local requests use the negotiated endpoint', () => {
  assert.equal(/(?:http|ws):\/\/127\.0\.0\.1:65123/.test(source), false);
});
