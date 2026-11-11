const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const ts = require('typescript');

function fixture(component, state, deferred = false) {
  const source = fs.readFileSync(path.join(__dirname, '../src/components/' + component + '.tsx'), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.React, jsxFactory: 'h', jsxFragmentFactory: 'Fragment'}}).outputText;
  let cursor = 0, resolve;
  const values = [], calls = [], effects = [];
  const promise = deferred ? new Promise(r => { resolve = r; }) : Promise.resolve();
  const context = {exports: {}, Fragment: 'fragment', h: (type, props, ...children) => ({type, props: props || {}, children}),
    require: name => {
      if (name === '@decky/ui') return {DialogButton: 'button', Focusable: 'group'};
      if (name === '@decky/api') return {call: async (...args) => { calls.push(args); await promise; if (state.fail) throw Error('fixture'); }};
      if (name === 'react') return {useState: initial => { const index = cursor++; if (!(index in values)) values[index] = initial;
        return [values[index], value => values[index] = value]; }, useRef: initial => { const index = cursor++;
          if (!(index in values)) values[index] = {current: initial}; return values[index]; }, useEffect: fn => effects.push(fn)};
      if (name.includes('useSteamcordState')) return {useSteamcordState: () => state};
      if (name.includes('host')) return {useHost: () => ({onWindows: true})};
      if (name.includes('CaptchaSolver')) return {openCaptchaSolver: () => calls.push(['captcha'])};
      if (name === './DiscordStartup') return {DiscordStartup: 'startup'};
      if (name.includes('i18n')) return {t: key => key};
      if (name.includes('Styled')) return {DANGER: '#ed4245', ONLINE: '#23a55a', focusHalo: () => ({})};
      if (name.includes('Icons') || name.startsWith('react-icons')) return new Proxy({}, {get: (_, key) => String(key)});
      throw Error(name);
    }};
  vm.runInNewContext(compiled, context);
  function render(props) { cursor = 0; return context.exports[component](props || {}); }
  function nodes(node) { return !node || typeof node !== 'object' ? [] : [node, ...node.children.flat(Infinity).flatMap(nodes)]; }
  return {render, nodes, calls, resolve: () => resolve?.()};
}

test('voice controls only exist in a confirmed active channel', () => {
  const f = fixture('VoiceSession', {me: {}});
  assert.equal(f.render(), null);
});

test('voice strip keeps explicit labels and confirmed Discord state while command is pending', async () => {
  const state = {vc: {channel_id: 'fixture', channel_name: 'A long channel name'}, me: {is_muted: false}};
  const f = fixture('VoiceSession', state, true);
  const buttons = f.nodes(f.render()).filter(n => n.type === 'button');
  assert.deepEqual(buttons.map(n => n.props['aria-label']), ['voice_mute', 'voice_deafen', 'voice_leave']);
  const command = buttons[0].props.onClick();
  buttons[0].props.onClick();
  assert.deepEqual(f.calls, [['toggle_mute']]);
  assert.equal(state.me.is_muted, false);
  assert.ok(f.nodes(f.render()).filter(n => n.type === 'button').every(n => n.props.disabled));
  f.resolve(); await command;
  state.me.is_muted = true;
  assert.equal(f.nodes(f.render()).find(n => n.type === 'button').props['aria-label'], 'voice_unmute');
});

test('failed action reports error without claiming the call changed', async () => {
  const state = {vc: {channel_id: 'fixture'}, me: {}, fail: true};
  const f = fixture('VoiceSession', state);
  await f.nodes(f.render()).find(n => n.type === 'button').props.onClick();
  assert.ok(f.nodes(f.render()).some(n => n.props.role === 'alert'));
  assert.equal(state.vc.channel_id, 'fixture');
});

test('sign-in loading, QR, scanned and CAPTCHA are separate states', () => {
  const f = fixture('DiscordSignIn', {});
  assert.ok(f.nodes(f.render()).some(n => n.type === 'startup'));
  const image = 'data:image/png;base64,Zml4dHVyZQ==';
  assert.equal(f.nodes(f.render({qr_login: image})).find(n => n.type === 'img').props.src, image);
  assert.ok(!f.nodes(f.render({qr_login: image, qr_scanned: true})).some(n => n.type === 'img'));
  const captcha = f.nodes(f.render({captcha_needed: true})).find(n => n.type === 'button');
  captcha.props.onClick(); assert.deepEqual(f.calls, [['captcha']]);
});

test('QR renderer rejects external URLs and oversized payloads', () => {
  const f = fixture('DiscordSignIn', {});
  for (const qr_login of ['https://example.org/pixel.png', 'javascript:alert(1)', 'data:image/png;base64,' + 'A'.repeat(600000)])
    assert.ok(!f.nodes(f.render({qr_login})).some(n => n.type === 'img'));
});
