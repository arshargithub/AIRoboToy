const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('tavi/web/workshop.js','utf8');
function setup(){
 const nodes={},requests=[],responses=[];let forbidden=0;
 const get=id=>nodes[id]??(nodes[id]={hidden:false,disabled:false,textContent:'',href:''});
 const block=()=>{forbidden++;throw Error('Forbidden capability');};
 const good=()=>({drive_connected:true,voice_model_file_present:true,budget:{available:true,spent_reserved_usd:17.983132,cap_usd:25},services:{family:{recognized:true,reachable:true,ready:true,url:'http://127.0.0.1:8783/'},adult:{recognized:true,reachable:true,ready:true,url:'http://127.0.0.1:8780/'},adventure:{recognized:true,reachable:true,ready:true,url:'http://127.0.0.1:8781/'}}});
 const env={document:{getElementById:get},AbortSignal,fetch:async(path,options)=>{requests.push({path,options});const value=responses.length?responses.shift():good();if(value instanceof Error)throw value;return{ok:!value.error,json:async()=>value};},navigator:{mediaDevices:{getUserMedia:block}},WebSocket:block,AudioContext:block};
 vm.createContext(env);vm.runInContext(code,env);
 return{get,requests,responses,good,get forbidden(){return forbidden;}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const t=setup();await settle();assert.equal(t.get('adult-open').href,'http://127.0.0.1:8780/');assert.equal(t.get('adventure-open').hidden,false);assert.match(t.get('budget').textContent,/17.98/);assert.equal(t.requests.length,1);assert.equal(t.get('family-childone').href,'http://127.0.0.1:8783/childone');assert.equal(t.get('family-childtwo').href,'http://127.0.0.1:8783/childtwo');assert.equal(t.get('family-adulttwo').href,'http://127.0.0.1:8783/adulttwo');assert.equal(t.forbidden,0);
 let status=t.good();status.services.adult={reachable:false,recognized:false,ready:false};t.responses.push(status);await t.get('refresh').onclick();assert.equal(t.get('adult-prepare').hidden,false);assert.equal(t.get('adult-open').hidden,true);
 t.responses.push({recognized:true,ready:true});await t.get('adult-prepare').onclick();assert.equal(t.requests.at(-2).path,'/api/prepare');assert.equal(JSON.parse(t.requests.at(-2).options.body).service,'adult');assert.equal(t.get('adult-open').hidden,false);
 status=t.good();status.drive_connected=false;status.services.adult={reachable:true,recognized:true,ready:false,url:'http://127.0.0.1:8780/'};status.services.adventure.url='https://unrelated.example/';t.responses.push(status);await t.get('refresh').onclick();assert.equal(t.get('adult-open').hidden,true);assert.equal(t.get('adventure-open').hidden,true);assert.match(t.get('help').textContent,/Reconnect/);
 t.responses.push(Error('offline'));await t.get('refresh').onclick();assert.match(t.get('error').textContent,/Check again/);assert.equal(t.get('refresh').disabled,false);assert.equal(t.get('adult-open').hidden,true);
 await t.get('refresh').onclick();assert.equal(t.get('adult-open').hidden,false);assert.equal(t.forbidden,0);
 status=t.good();status.budget={available:false};status.voice_model_file_present=false;t.responses.push(status);await t.get('refresh').onclick();assert.match(t.get('budget').textContent,/Ledger unavailable/);assert.match(t.get('model').textContent,/unavailable/);assert.equal(t.forbidden,0);
 console.log('Workshop actual UI: readiness/explicit prepare/error retry, missing drive/ledger, foreign URL suppression, no automatic recording/models/remote capabilities pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
