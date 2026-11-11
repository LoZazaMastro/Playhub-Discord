const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const source=fs.readFileSync('defaults/steamcord_client.js','utf8');
const start=source.indexOf('            let reconnectTimer = null;');
const end=source.indexOf('\n            connect();',start)+'\n            connect();'.length;
function fixture(){
 const timers=new Map(),intervals=new Map(),sockets=[],ready=[],pagehide=[],delays=[];let id=0;
 const foreign=()=>{}, dispatcher={_interceptors:[foreign],addInterceptor(fn){this._interceptors.push(fn)}};
 const window={__sc_bridgeUrl:()=> 'ws://127.0.0.1:55000/socket',STEAMCORD_IS_VESKTOP:true,
 setTimeout(fn,delay){timers.set(++id,{fn,delay});return id},clearTimeout(key){timers.delete(key)},
 setInterval(fn,delay){intervals.set(++id,{fn,delay});return id},clearInterval(key){intervals.delete(key)},
 addEventListener(type,fn){if(type==='pagehide')pagehide.push(fn)}};
 class WebSocket{constructor(){this.readyState=0;this.listeners={};this.sent=[];sockets.push(this)}addEventListener(type,fn){this.listeners[type]=fn}send(message){this.sent.push(JSON.parse(message))}close(){this.readyState=3;this.onclose?.({})}}
 vm.runInNewContext(source.slice(start,end),{window,WebSocket,encodeURIComponent,console:{log(){},error(){}},FluxDispatcher:dispatcher,setTimeout:fn=>{delays.push(fn)},
 Vencord:{Webpack:{onceReady:{then:fn=>ready.push(fn)},waitFor:(key,fn)=>fn(),findByProps:()=>({setEchoCancellation(){}}),findStore:()=>({getEchoCancellation:()=>true}),Common:{UserStore:{getCurrentUser:()=>null}}}}});
 return{window,sockets,timers,intervals,dispatcher,foreign,ready,pagehide,delays,runTimer(){const [key,t]=timers.entries().next().value;timers.delete(key);t.fn();return t.delay}};
}
test('failed bridge reconnects back off without duplicate timer, intervals or foreign interceptor removal',()=>{
 const f=fixture(),other=()=>{};f.dispatcher.addInterceptor(other);
 assert.equal(f.sockets.length,1);assert.equal(f.intervals.size,3);
 const delays=[];
 for(let i=0;i<7;i++){
   const socket=f.sockets.at(-1);socket.close();socket.onclose({});
   assert.equal(f.intervals.size,0);assert.equal(f.timers.size,1);
   assert.deepEqual(f.dispatcher._interceptors,[f.foreign,other]);
   delays.push(f.runTimer());assert.equal(f.intervals.size,3);
   assert.equal(f.dispatcher._interceptors.length,3);
 }
 assert.deepEqual(delays,[100,250,500,1000,2000,3000,3000]);
 f.window.__sc_disposeBridge();assert.equal(f.intervals.size,0);assert.equal(f.timers.size,0);
 assert.deepEqual(f.dispatcher._interceptors,[f.foreign,other]);
});
test('explicit Retry advances one pending reconnect and page disposal retires its timers',()=>{
 const f=fixture();f.sockets[0].close();assert.equal(f.timers.size,1);
 f.window.__sc_reconnectBridge();assert.equal(f.sockets.length,2);assert.equal(f.timers.size,0);
 f.window.__sc_reconnectBridge();assert.equal(f.sockets.length,2);
 for(const ready of f.ready)ready();
 f.pagehide[0]();assert.equal(f.intervals.size,0);assert.equal(f.timers.size,0);
 f.window.__sc_reconnectBridge();assert.equal(f.sockets.length,2);
});

test('an asynchronous reply from the old connection cannot resolve an RPC in a new backend session',async()=>{
 const f=fixture();const old=f.sockets[0];old.readyState=1;
 const request={type:'$set_echo_cancellation',enabled:true,increment:0};
 const pending=old.listeners.message({data:JSON.stringify(request)});
 assert.equal(f.delays.length,1);old.close();f.runTimer();
 const current=f.sockets[1];current.readyState=1;
 f.delays.shift()();await pending;
 assert.equal(old.sent.length,0);assert.equal(current.sent.length,0);
 await old.listeners.message({data:JSON.stringify(request)});
 assert.equal(f.delays.length,0,'retired socket cannot begin another command');
 const valid=current.listeners.message({data:JSON.stringify(request)});
 f.delays.shift()();await valid;
 assert.equal(current.sent.length,1);assert.equal(current.sent[0].increment,0);
 assert.equal(current.sent[0].result.echoCancellation,true);
 f.window.__sc_disposeBridge();
});
