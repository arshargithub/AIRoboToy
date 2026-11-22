'use strict';
const $=id=>document.getElementById(id),session=crypto.randomUUID().replaceAll('-','');let reported=null,scope=null;
function show(name){for(const k of ['intro','account','review','request'])$(k).hidden=k!==name;}
function choices(){return {session_id:session,status:reported,scope:reported==='enabled'?scope:'not_checked'};}
function update(){reported=document.querySelector('input[name=status]:checked')?.value??null;scope=document.querySelector('input[name=scope]:checked')?.value??null;$('project').hidden=reported!=='enabled';$('next').disabled=!reported||reported==='enabled'&&!scope;}
for(const input of document.querySelectorAll('input'))input.onchange=update;
$('continue').onclick=()=>show('account');$('back').onclick=()=>show('intro');$('edit').onclick=()=>show('account');
$('next').onclick=()=>{if($('next').disabled)return;
 const confirmed=reported==='enabled'&&scope!=='not_checked';
 $('result-title').textContent=confirmed?'Reported ZDR ready for verification':'Account status recorded without ZDR confirmation';
 $('result-help').textContent=confirmed?'You report ZDR for the project. This is not account verification yet. This optional record does not change recording consent or test scope.':'You can save this optional account-status report. ZDR approval is not an engineering prerequisite. Provider guidance remains documented; this does not establish an exemption or approval. No support request or account change is sent.';
 show('review');};
$('save').onclick=async()=>{const body=choices();$('save').disabled=true;$('error').textContent='';
 try{const response=await fetch('/readiness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(5000)});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not save status');
  $('saved').textContent='Saved on this Mac. This optional report is complete. Recording consent and test scope are unchanged; no account task is needed to continue engineering.';$('edit').disabled=true;
 }catch(error){$('error').textContent=error.message+' Your choices are still here. Retry Save or download them below.';$('save').disabled=false;$('download').hidden=false;}};
$('download').onclick=()=>{const data={kind:'paprika_parent_readiness_browser_recovery',...choices(),child_cloud_authorized:false};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='paprika-parent-readiness.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

$('prepare-request').onclick=()=>show('request');
$('request-back').onclick=()=>show('intro');
$('copy-request').onclick=async()=>{
 try{await navigator.clipboard.writeText($('request-draft').value);$('copy-status').textContent='Copied. Review and send it yourself through OpenAI Help when ready. Nothing has been sent yet.';}
 catch{ $('request-draft').focus();$('request-draft').select();$('copy-status').textContent='The draft is selected. Press Command+C on Mac or Ctrl+C elsewhere to copy, then send it through OpenAI Help. Nothing has been sent yet.'; }
};
