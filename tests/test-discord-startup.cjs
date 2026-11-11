const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test'),ts=require('typescript');
const compile=path=>ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,jsxFactory:'h'}}).outputText;
function fixture(reply={ready:true}, retryReply={ok:true}){
  let clock=1000,cursor=0,request;
  const values=[],effects=[],intervals=[],timeouts=new Map(),calls=[];let timer=0;
  const date={now:()=>clock};
  const deadline={exports:{},Date:date};vm.runInNewContext(compile('src/connectionDeadline.ts'),deadline);
  const context={exports:{},Date:date,Error,Promise,
    setTimeout:fn=>{timeouts.set(++timer,fn);return timer},clearTimeout:id=>timeouts.delete(id),
    setInterval:fn=>{intervals.push(fn);return intervals.length},clearInterval:()=>{},
    h:(type,props,...children)=>({type,props:props||{},children}),
    require:name=>{
      if(name==='@decky/ui')return{DialogButton:'button'};
      if(name==='@decky/api')return{call:async method=>{calls.push(method);if(method==='retry_connection')return typeof retryReply==='function'?retryReply():retryReply;if(reply instanceof Error)throw reply;return reply}};
      if(name==='react')return{useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next}]},useRef:initial=>{const i=cursor++;if(!(i in values))values[i]={current:initial};return values[i]},useEffect:fn=>effects.push(fn)};
      if(name.includes('connectionDeadline'))return deadline.exports;
      if(name.includes('i18n'))return{t:key=>key};
      if(name==='react-icons/fa')return{FaDiscord:'icon'};
      throw Error(name);
    }};
  vm.runInNewContext(compile('src/components/DiscordStartup.tsx'),context);
  const render=()=>{cursor=0;effects.length=0;return context.exports.DiscordStartup({})};
  const flat=n=>!n||typeof n!=='object'?[]:[n,...n.children.flat(Infinity).flatMap(flat)];
  return{calls,timeouts,deadline,render,flat,async mount(){const n=render();for(const fn of effects)fn();await this.flush();return n},async flush(){for(let i=0;i<10;i++)await Promise.resolve()},async advance(ms){clock+=ms;for(const fn of intervals)fn();await this.flush()},button(){return flat(render()).find(n=>n.type==='button')},now:()=>clock};
}
test('waiting is bounded and reopening preserves the original deadline',async()=>{
  const f=fixture();await f.mount();assert.ok(f.flat(f.render()).some(n=>n.props.role==='status'));assert.equal(f.button(),undefined);
  await f.advance(20000);assert.ok(f.flat(f.render()).some(n=>n.props.role==='alert'));assert.ok(f.button());
  assert.equal(f.deadline.exports.connectionStarted(f.now()),1000);
  f.deadline.exports.connectionCompleted();assert.equal(f.deadline.exports.connectionStarted(f.now()),21000);
});
test('an unavailable bridge and repeated RPC failure stop the spinner early',async()=>{
  const f=fixture({ready:false});await f.mount();await f.advance(6000);assert.ok(f.button());
  const g=fixture(Error('offline'));await g.mount();await g.advance(2000);assert.ok(g.button());
});

test('a loaded bridge without QR or account does not reset the deadline on QAM reopen',async()=>{
  const f=fixture();await f.mount();await f.advance(12000);
  f.deadline.exports.connectionProgress({loaded:true,logged_in:false,qr_login:null});
  assert.equal(f.deadline.exports.connectionStarted(f.now()),1000);
  await f.advance(8000);
  f.deadline.exports.connectionProgress({loaded:true,logged_in:false,qr_login:null});
  assert.ok(f.button());
  assert.equal(f.deadline.exports.connectionStarted(f.now()),1000);
  for(const progress of [{logged_in:true},{qr_login:'data:image/png;base64,qr'},{qr_scanned:true},{captcha_needed:true}]){
    f.deadline.exports.connectionProgress({loaded:true,...progress});
    assert.equal(f.deadline.exports.connectionStarted(f.now()),f.now());
  }
});
test('Retry is single-flight and only resets the deadline after backend acceptance',async()=>{
  let release;const f=fixture({ready:true},()=>new Promise(r=>release=r));await f.mount();await f.advance(20000);
  const button=f.button();button.props.onClick();button.props.onClick();await f.flush();
  assert.equal(f.calls.filter(x=>x==='retry_connection').length,1);assert.equal(f.button().props.disabled,true);
  release({ok:true});await f.flush();assert.equal(f.button(),undefined);
  await f.advance(20000);assert.ok(f.button());
});
test('a rejected retry remains actionable and never reports a connection',async()=>{
  const f=fixture({ready:true},{ok:false});await f.mount();await f.advance(20000);f.button().props.onClick();await f.flush();assert.ok(f.button());assert.equal(f.button().props.disabled,false);
});
test('sign-in and connection guidance is concise for all Playhub languages',()=>{
  const languages=['english','italian','french','german','spanish','portuguese','russian','ukrainian','japanese','koreana','schinese','hindi','dutch','polish'];
  for(const language of languages){
    const c={exports:{},window:{LocalizationManager:{m_strLanguage:language}},navigator:{language:'en'}};vm.runInNewContext(compile('src/i18n.ts'),c);
    for(const key of ['initializing','initializing_slow','connection_failed','connection_retry','login_vesktop_hint_windows','vesktop_missing_windows','captcha_unavailable']){
      const text=c.exports.t(key);assert.notEqual(text,key);assert.ok(text.length<240);assert.equal(/Vesktop|Vencord|Repair|tray|Desktop Mode/.test(text),false,language+': '+key);
    }
  }
});
