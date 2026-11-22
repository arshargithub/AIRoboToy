const {test}=require('node:test'),assert=require('node:assert/strict');
const {MacCheckGuide}=require('../tavi/web/mac-check-guide.js');
function guide(){const seen=[],stops=[];const g=new MacCheckGuide({render:g=>seen.push(g.stage),stop:()=>stops.push('stop')});g.start();return{g,seen,stops};}
function view(id,complete=null,playing=false){return{playing,loading:false,state:{accepted_response_id:id,completed_response_id:complete}};}
test('quiet reply must finish before no-name follow-up; replacement must finish before completion',()=>{
 const {g,stops}=guide();assert.equal(g.stage,'ask');g.observe(view('first'));assert.equal(g.stage,'quiet');assert(g.copy()[2].startsWith('Paprika,'));
 g.observe(view('first','first',true));assert.equal(g.stage,'quiet');g.observe(view('first','first'));assert.equal(g.stage,'followup');assert(!g.copy()[2].includes('Paprika'));
 g.observe(view('second'));assert.equal(g.stage,'wait');g.observe(view('second',null,true));assert.equal(g.stage,'interrupt');assert(g.copy()[2].includes('tiny robot'));
 g.observe(view('third'));assert.equal(g.stage,'replacement');g.observe(view('third','third',true));assert.equal(g.stage,'replacement');g.observe(view('third','third'));assert.equal(g.stage,'review');assert.equal(stops.length,1);assert.equal(g.report('worked','').completed_sequence,true);
});
test('failed and partial checks stay incomplete and turn microphone off once',()=>{
 const {g,stops}=guide();g.observe(view('first'));g.finish('Recognition failed');g.finish('again');assert.equal(g.stage,'review');assert.equal(stops.length,1);assert.equal(g.report('problem','a'.repeat(1500)).note.length,1000);assert.equal(g.report('problem','').completed_sequence,false);assert.equal(g.report('problem','').unscored_feedback,true);
});
test('a ready audio prefix never counts as completed physical playback',()=>{
 const {g}=guide();g.observe(view('first'));g.observe(view('first'));assert.equal(g.stage,'quiet');g.finish();
});
