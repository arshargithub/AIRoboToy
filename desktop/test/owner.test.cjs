const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {CoreOwner}=require('../owner.cjs');
test('ownership record rejects broad permissions, malformed protocol and symlinks',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'paprika-owner-'));try{
  fs.mkdirSync(path.join(root,'.tavi/mac'),{recursive:true});const file=path.join(root,'.tavi/mac/core.json'),owner=new CoreOwner(root);
  assert.equal(owner.read(),null);fs.writeFileSync(file,JSON.stringify({pid:123,port:8785,protocol:1,token:'a'.repeat(64),instance:'b'.repeat(32)}),{mode:0o644});fs.chmodSync(file,0o644);assert.throws(()=>owner.read(),/ownership/);
  fs.chmodSync(file,0o600);assert.equal(owner.read().pid,123);
  fs.unlinkSync(file);fs.symlinkSync('/etc/hosts',file);assert.throws(()=>owner.read(),/ownership/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('core verification rejects a different service instance',async()=>{
 const owner=new CoreOwner('/tmp/unused');owner.request=async()=>({service:'paprika-core',protocol:1,instance:'wrong'});
 await assert.rejects(owner.verify({instance:'expected'}),/Another service/);
});
test('concurrent ensure calls share a single owner start',async()=>{
 const owner=new CoreOwner('/tmp/unused');let calls=0;owner._ensure=async()=>{calls++;await new Promise(resolve=>setImmediate(resolve));return 'ready';};
 assert.deepEqual(await Promise.all([owner.ensure(),owner.ensure()]),['ready','ready']);assert.equal(calls,1);
});
function stoppedFixture(){
 const {spawnSync}=require('node:child_process'),root=fs.mkdtempSync(path.join(os.tmpdir(),'paprika-dead-owner-'));
 fs.mkdirSync(path.join(root,'.tavi/mac'),{recursive:true});const file=path.join(root,'.tavi/mac/core.json');
 const dead=spawnSync(process.execPath,['-e','process.exit(0)']);
 const record={pid:dead.pid,port:8785,protocol:1,token:'a'.repeat(64),instance:'b'.repeat(32)};
 fs.writeFileSync(file,JSON.stringify(record),{mode:0o600});const owner=new CoreOwner(root);owner.record=record;
 owner.verify=async()=>{throw Error('Stopped fixture core');};return{root,file,record,owner};
}
test('quit after an owned core crash clears only its dead ownership record',async()=>{
 const t=stoppedFixture();try{await t.owner.stop();assert.equal(t.owner.read(),null);assert.equal(t.owner.record,null);}finally{fs.rmSync(t.root,{recursive:true,force:true});}
});
test('unverifiable live PID is left intact and shutdown fails honestly',async()=>{
 const t=stoppedFixture();try{t.owner.record={...t.record,pid:process.pid};fs.writeFileSync(t.file,JSON.stringify(t.owner.record));
  await assert.rejects(t.owner.stop(),/Stopped fixture core/);assert.equal(t.owner.read().pid,process.pid);
 }finally{fs.rmSync(t.root,{recursive:true,force:true});}
});
test('late cleanup of a dead instance cannot unlink a replacement instance',async()=>{
 const t=stoppedFixture();try{fs.writeFileSync(t.file,JSON.stringify({...t.record,pid:process.pid,instance:'c'.repeat(32)}));await t.owner.stop();assert.equal(t.owner.read().instance,'c'.repeat(32));}
 finally{fs.rmSync(t.root,{recursive:true,force:true});}
});
