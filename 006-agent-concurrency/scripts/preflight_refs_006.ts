// Static native provenance/manifest checks. Never queries Docker or a remote host.
import {readFile,realpath,stat} from 'node:fs/promises';
import {resolve,join,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
const [atlas,dataRoot,mapPath,...paths]=process.argv.slice(2);
const api=async(p:string)=>import(pathToFileURL(join(atlas,p)).href);
const {loadManifest,readTask,digest}=await api('runner/manifest.ts');
const {frozenIdentity,runtimeIdentity,frozenRecipe,validPair,imageId}=await api('runner/host/images.ts');
const {gradingTask}=await api('grading/task.ts');
const data=await realpath(dataRoot),map=JSON.parse(await readFile(mapPath,'utf8'));
const frozen=await frozenIdentity(true);
if(map.version!==1||map.host?.platform!=='linux/amd64'||!map.host.daemonId||map.runtimeSha256!==await runtimeIdentity()||!isDeepStrictEqual(map.frozen,frozen.identity))throw Error('Native image-map frozen/runtime/amd64 identity differs');
if(!isDeepStrictEqual(Object.keys(map.tasks).sort(),frozen.tasks.map((t:any)=>t.id).sort()))throw Error('Native image map is incomplete');
async function local(path:string){
 const marker='/atlas/data/',index=path.indexOf(marker);
 if(index<0)throw Error('Unresolved image-map reference: '+path);
 const resolved=await realpath(resolve(data,path.slice(index+marker.length)));
 if(!resolved.startsWith(data+sep)||!(await stat(resolved)).isFile())throw Error('Image-map reference escapes data or is not a file');
 return resolved;
}
for(const id of Object.keys(map.tasks)){
 const entry=map.tasks[id],task=await readTask(id),recipe=await frozenRecipe(id),grading=await gradingTask(id);
 if(entry.taskId!==id||entry.taskDigest!==task.digest||entry.recipeSha256!==recipe.recipeSha256||entry.lockSha256!==recipe.lockSha256||entry.frozenImage!==task.image||!imageId(entry.image)||!isDeepStrictEqual(entry.preparation,recipe.preparation)||!validPair(entry.check.base,entry.check.reference))throw Error('Unchecked/stale native image: '+id);
 for(const [grade,hash] of [[entry.check.base,entry.check.baseSha256],[entry.check.reference,entry.check.referenceSha256]]){
  const raw=await readFile(await local(join(grade.directory,'tests.json')),'utf8');
  if(digest(raw)!==hash||!isDeepStrictEqual(JSON.parse(raw),grade)||grade.image!==entry.image||grade.taskMetadataHash!==grading.metadataHash||grade.hiddenHash!==grading.hiddenHash||!isDeepStrictEqual(grade.preparation??[],entry.preparation))throw Error('Native check evidence changed: '+id);
  await local(grade.stdoutPath);await local(grade.stderrPath);
 }
}
for(const path of paths){
 const loaded=await loadManifest(path);
 for(const run of loaded.runs)if(!map.tasks[run.taskId])throw Error('Manifest task has no checked image: '+run.taskId);
}
console.log(JSON.stringify({manifests:paths.length,checked_native_tasks:Object.keys(map.tasks).length,static_only:true}));
