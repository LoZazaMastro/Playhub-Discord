import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import { promisify } from 'node:util';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';

const root = path.dirname(path.dirname(url.fileURLToPath(import.meta.url)));
const python = `import runpy,json,tarfile,pathlib
r=pathlib.Path(__import__('sys').argv[1]); d=runpy.run_path(str(r/'scripts/derive-vesktop.py'))
with __import__('zipfile').ZipFile(r/'runtime/Vesktop-1.6.8-playhub.1-win.zip') as z: _,a=d['unpack_asar'](z.read('resources/app.asar'))
w=a['dist/js/arRpcWorker.js'][1].decode();sm=json.loads(a['dist/js/arRpcWorker.js.map'][1]);i=next(i for i,n in enumerate(sm['sources']) if n.endswith('/src/process/index.js'));n=next(i for i,n in enumerate(sm['sources']) if n.endswith('/src/process/native/win32.js'))
with tarfile.open(r/'runtime/sources/arrpc-source.tar.gz') as t:b=t.extractfile(next(m for m in t.getmembers() if m.name.endswith('/src/process/index.js'))).read().decode()
start=w.index('async scan()');end=w.index('};var Oi=',start)
print(json.dumps({'before-process.js':b,'candidate-process.js':sm['sourcesContent'][i],'actual-win32.js':sm['sourcesContent'][n],'compiled-process.js':'export default class ProcessServer{'+w[start:end]+'}'}))`;
const inputs = JSON.parse(execFileSync('python',['-X','utf8','-B','-c',python,root],{encoding:'utf8',windowsHide:true}));
let checks = 0;
function check(value, message) { assert.ok(value, message); checks++; }
async function fixture(filename) {
  let output = '[]', failure = null;
  const logs = [], calls = [];
  const context = vm.createContext({process: {platform: 'win32', env: {}}, console: {log: (...v) => logs.push(v)}, setInterval() { throw Error('no real timers'); }, Rs:null, A:(...v)=>logs.push(v), fe:{}, ks:{}, Is:{}});
  function module(exports, id) {
    return new vm.SyntheticModule(Object.keys(exports), function () { for (const [k,v] of Object.entries(exports)) this.setExport(k,v); }, {context, identifier:id});
  }
  const native = new vm.SourceTextModule(inputs['actual-win32.js'], {context,identifier:'file:///C:/fixture/src/process/native/win32.js'});
  const fakeExec = (exe,args,callback) => { calls.push({exe,args}); callback(failure,output,''); };
  fakeExec[promisify.custom] = async (exe,args) => { calls.push({exe,args}); if(failure) throw failure; return {stdout:output,stderr:''}; };
  await native.link(spec => {
    if (spec === 'child_process') return module({execFile: fakeExec},spec);
    if (spec === 'util') return module({promisify},spec);
    throw Error(spec);
  });
  await native.evaluate();
  context.Rs = native.namespace;
  const processModule = new vm.SourceTextModule(inputs[filename], {context,identifier:'file:///C:/fixture/src/process/index.js', initializeImportMeta(meta) { meta.url='file:///C:/fixture/src/process/index.js'; }});
  await processModule.link(spec => {
    if (spec === 'node:fs') return module({default:{}},spec);
    if (spec === 'path') return module({dirname:path.dirname,join:path.join},spec);
    if (spec === 'url') return module({fileURLToPath:url.fileURLToPath},spec);
    if (spec === './native/index.js') return module({win32:native.namespace},spec);
    throw Error(spec);
  });
  await processModule.evaluate();
  const events = [];
  const server = Object.create(processModule.namespace.default.prototype);
  server.handlers = {message: (...args) => events.push(args)};
  server.DetectableDB = [{id:'fixture-game',name:'Fixture Game',executables:[{name:'game.exe',is_launcher:false}]}];
  return {server,events,logs,calls,native,set(data) { output=data;failure=null; },fail() { failure=new Error('synthetic OS query failure'); }};
}
const processRows = JSON.stringify([{ProcessId:7,ExecutablePath:'C:\\fixture\\game.exe',CommandLine:'"C:\\fixture\\game.exe" --option'}]);
const malformed = '[{"ProcessId":7,"ExecutablePath":"C:\\\\fixture\\\\game.exe","CommandLine":"private' + String.fromCharCode(1) + 'fixture"}]';
for (const filename of (process.argv.includes('--before') ? ['before-process.js'] : ['before-process.js','candidate-process.js','compiled-process.js'])) {
  const f = await fixture(filename);
  f.set(processRows);
  const rows = await f.native.namespace.getProcesses();
  check(rows.length===1 && rows[0][0]===7 && rows[0][1]==='C:\\fixture\\game.exe','actual native parser returns valid rows');
  await f.server.scan();
  check(f.events.length===1 && f.events[0][1].args.activity.name==='Fixture Game','actual scanner publishes valid detected game');
  f.set(malformed);
  let rejected=false;
  try { await f.server.scan(); } catch(e) { rejected=e.name==='SyntaxError'; }
  if(filename==='before-process.js') {
    if(process.argv.includes('--before')) check(!rejected,'Malformed process snapshot must not reject the actual scanner (parent RED)');
    check(rejected,'PARENT RED: malformed OS JSON rejects actual scan, escaping worker interval');
    check(f.events.length===1,'parent has not synthesized game closure');
  } else {
    check(!rejected,'candidate catches actual native JSON parse failure');
    check(f.events.length===1,'failed scan emits no false game closure or replacement');
    check(f.logs.some(v=>v.some(s=>typeof s==='string'&&s.includes('process enumeration unavailable'))),'bounded constant diagnostic');
    check(!JSON.stringify(f.logs).includes('private'),'private process payload is not logged');
    f.fail();
    await f.server.scan();
    check(f.events.length===1,'OS query failure also preserves current activity');
    f.set(processRows);
    await f.server.scan();
    check(f.events.length===2 && f.events[1][1].args.activity.name==='Fixture Game','next existing scan recovers genuine presence');
    f.set('[]');
    await f.server.scan();
    check(f.events.length===3 && f.events[2][1].args.activity===null,'genuine successful empty snapshot clears activity');
    await f.server.scan();
    check(f.events.length===3,'no repeated false lost activity');
    check(f.calls.every(c=>c.exe==='powershell.exe'&&c.args.at(-1).includes('Get-CimInstance Win32_Process')),'real production native command exercised with fake process boundary');
  }
}
console.log(JSON.stringify({checks,parentActualSyntaxErrorReproduced:true,candidate:'PASS',compiledDerivedWorker:'PASS',boundaries:'actual native parser + actual scan; only execFile fake; no profiles/provider/UI/process start'},null,2));

