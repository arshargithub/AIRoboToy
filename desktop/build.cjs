'use strict';
const fs=require('node:fs'),path=require('node:path'),{packager}=require('@electron/packager');
async function build(){
 const root=path.resolve(__dirname,'..');
 fs.writeFileSync(path.join(__dirname,'development.json'),JSON.stringify({projectRoot:root})+'\n');
 try{
  const output=await packager({dir:__dirname,out:path.join(root,'.tavi/mac/build'),name:'Paprika',platform:'darwin',arch:process.arch,
   appBundleId:'local.paprika.prototype',appVersion:require('./package.json').version,overwrite:true,prune:true,asar:true,
   ignore:[/\/test($|\/)/,/\/build\.cjs$/,/\/package-lock\.json$/],
   extendInfo:{NSMicrophoneUsageDescription:'Paprika listens locally when you choose Start. Engaged conversation text may be sent to OpenAI if you enable online replies.'}});
  console.log(output.join('\n'));
 }finally{fs.unlinkSync(path.join(__dirname,'development.json'));}
}
build().catch(error=>{console.error(error);process.exitCode=1;});
