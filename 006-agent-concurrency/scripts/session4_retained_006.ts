// Read retained evidence, or grade explicitly pending work on a checked new host.
// Never dispatches agents, changes execution rows, or relaxes artifact guards.
import {readFile,writeFile,mkdir,access,rename,lstat,readdir,readlink} from 'node:fs/promises';
import {resolve,join,dirname,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
const sha=(s:any)=>createHash('sha256').update(s).digest('hex');
const json=async(p:string)=>JSON.parse(await readFile(p,'utf8'));
const [mode,location,atlas]=process.argv.slice(2);
if(execFileSync('git',['-C',atlas,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='279889b8f42c607344781766503602a8c462f5df')throw Error('Wrong ATLAS pin');
const api=async(p:string)=>import(pathToFileURL(join(atlas,p)).href);
const {artifactText,readEvidence}=await api('grading/evidence.ts');
export function localPath(path:string,data:string){
 const marker='/atlas/data/',index=path.indexOf(marker);
 if(index<0)throw Error('Unrecognized retained artifact path');
 const mapped=resolve(data,path.slice(index+marker.length));
 if(!mapped.startsWith(resolve(data)+sep))throw Error('Retained path escapes data');
 return mapped;
}
// Bind even unsafe workspace symlinks without following them. The pinned native
// snapshot checker still decides whether that workspace can be graded.
async function retainedTree(path:string){
 const entries:any[]=[];
 async function walk(dir:string,relative=''){
  for(const name of (await readdir(dir)).sort()){
   if(name==='.git')continue;
   const full=join(dir,name),rel=relative?relative+'/'+name:name,s=await lstat(full);
   entries.push([rel,s.mode&0o777,s.isSymbolicLink()?['link',await readlink(full)]:s.isDirectory()?['dir']:s.isFile()?['file',sha(await readFile(full))]:['special']]);
   if(s.isDirectory())await walk(full,rel);
  }
 }
 await walk(path);return sha(JSON.stringify(entries));
}
async function evidence(row:any,data:string){
 const text=await artifactText(localPath(row.trace_path,data)),execution=JSON.parse(text);
 const proxy=localPath(execution.proxy_log,data),raw=await artifactText(proxy);
 const value=await readEvidence(row.backend,row.harness,{...execution,proxy_log:proxy});
 const responses=value.raw.filter((r:any)=>r.event==='response');
 return {text,execution,value,proof:{trace_sha256:sha(text),proxy_sha256:sha(raw),workspace_sha256:await retainedTree(join(dirname(localPath(row.trace_path,data)),'workspace'))},
  metrics:{tokens_in:value.tokens.input,tokens_out:value.tokens.output,tokens_cached:value.tokens.cached,inference_s:value.inferenceS,
   turns:value.raw.filter((r:any)=>r.event==='request').length,tool_calls:value.toolCalls.length,model_latency_s:responses.map((r:any)=>r.inference_s)}};
}
async function atomic(path:string,value:any){
 await mkdir(dirname(path),{recursive:true});const tmp=path+'.tmp';await writeFile(tmp,JSON.stringify(value,null,2)+'\n');await rename(tmp,path);
}
if(mode==='extract'){
 const row=JSON.parse(readFileSync(0,'utf8')),e=await evidence(row,location);
 console.log(JSON.stringify({metrics:e.metrics,proof:e.proof,execution_host:e.execution.hostImage.host}));
}else if(mode==='grade'){
 const root=location,data=join(process.cwd(),'data'),pendingPath=join(root,'results/session4/pending_native.json');
 const pending=await json(pendingPath);
 const {loadHostMap}=await api('runner/host/images.ts');
 const {map,sha256}=await loadHostMap('data/rocm-recipes-006-native-session4/image-map.json');
 if(map.host.platform!=='linux/amd64')throw Error('Pending production grade requires checked amd64 host');
 const originalMap=await json(join(root,'results/session4/execution-image-map.json'));
 const {Store}=await api('runner/store.ts'),{gradeTests}=await api('grading/grader.ts'),{gradingTask}=await api('grading/task.ts');
 const {captureProtection,compareProtection}=await api('grading/tamper.ts'),{categorize}=await api('grading/taxonomy.ts'),{parseStatus}=await api('grading/claim.ts');
 for(const item of pending.runs){
  if(item.status==='complete')continue;
  const store=new Store('data/rocm-recipes-006/atlas.db');let row:any;
  try{row=store.row(item.row.run_id);}finally{store.close();}
  if(!isDeepStrictEqual({...row},item.row))throw Error('Pending execution row changed');
  const e=await evidence(row,data);
  if(!isDeepStrictEqual(e.proof,item.proof))throw Error('Retained pending evidence changed');
  if(sha(await readFile(join(root,'results/session4/execution-image-map.json')))!==e.execution.hostImage.mapSha256)throw Error('Original execution map changed');
  const old=e.execution.hostImage.entry,entry=map.tasks[row.task_id];
  if(!isDeepStrictEqual(originalMap.tasks[row.task_id],old))throw Error('Original task image entry changed');
  for(const field of ['taskId','taskDigest','recipeSha256','lockSha256','frozenImage','preparation'])if(!isDeepStrictEqual(old[field],entry[field]))throw Error('New host frozen recipe differs: '+field);
  if(!isDeepStrictEqual(originalMap.frozen,map.frozen)||originalMap.runtimeSha256!==map.runtimeSha256)throw Error('New host frozen/runtime identity differs');
  const fingerprint=sha(JSON.stringify({row,proof:e.proof,gradingHost:map.host,mapSha256:sha256}));
  const directory=join(data,'grading/post-session',row.run_id),path=join(directory,'grade.json');let record:any;
  try{await access(path);record=JSON.parse(await artifactText(path));if(record.fingerprint!==fingerprint)throw Error('Pending grade inputs changed');}
  catch(error:any){
   if(error.code!=='ENOENT')throw error;
   const workspace=join(dirname(localPath(row.trace_path,data)),'workspace');
   const task=await gradingTask(row.task_id);
   const tests=await gradeTests(workspace,{...task,image:entry.image,preparation:entry.preparation},join(directory,'tests'));
   let protection=null;
   try{protection=compareProtection(JSON.parse(await artifactText(join(dirname(localPath(row.trace_path,data)),'protection-before.json'))),await captureProtection(workspace,row.task_id));}catch{}
   const category=categorize({infra:tests.testsPassed===null||!protection,endReason:row.end_reason,tamper:protection?.tamper??false,testsPassed:tests.testsPassed,claim:parseStatus(e.value.finalMessage)??'none'});
   record={runId:row.run_id,fingerprint,executionRow:row,tests,protection,category,execution_host:e.execution.hostImage.host,grading_host:map.host,
    grading_image_map_sha256:sha256,grading_image:entry.image,host_changed:!isDeepStrictEqual(map.host,e.execution.hostImage.host),frozen_recipes_verified:true,proof:e.proof,status:'complete'};
   await mkdir(directory,{recursive:true});const body=JSON.stringify(record);
   if(Buffer.byteLength(body)>32*1024*1024)throw Error('Pending grade exceeds strict artifact bound');
   await writeFile(path,body,{flag:'wx',mode:0o600});
  }
  const reportPath=join(data,'rocm-recipes-006/live/c16/runs.json'),report=await json(reportPath),out=report.rows.find((r:any)=>r.run_id===row.run_id);
  if(!out||(!out.native_grade_pending&&out.native_grade_record!==path))throw Error('Pending export row missing');
  Object.assign(out,{native_grade_pending:false,excluded:record.category==='infra_error',tests_passed:record.tests.testsPassed,tamper:record.protection?.tamper??null,
   category:record.category,solved_by_tests:record.tests.testsPassed===true&&record.protection?.tamper===false&&record.category!=='infra_error',native_grade_record:path,
   execution_host:record.execution_host,grading_host:record.grading_host,grading_host_changed:record.host_changed});
  out.flags=(out.flags??[]).filter((f:string)=>!f.startsWith('Native tests pending'));
  item.status='complete';item.grade_record=path;item.grading_host=record.grading_host;item.execution_host=record.execution_host;
  report.pending_native_grades=report.rows.filter((r:any)=>r.native_grade_pending).length;
  report.complete=report.pending_native_grades===0&&report.pending_mac_grades===0;
  await atomic(reportPath,report);await atomic(join(root,'results/atlas/scored/live/c16/runs.json'),report);await atomic(pendingPath,pending);
  await atomic(join(root,'results/grading/counts/c16.json'),{level:'c16',stage:'c16',pending_mac_grades:report.pending_mac_grades,pending_native_grades:report.pending_native_grades,run_ids:report.rows.filter((r:any)=>r.grading_pending).map((r:any)=>r.run_id)});
  console.log('Post-session native grade: '+JSON.stringify({run_id:row.run_id,...record,executionRow:undefined,tests:record.tests,proof:undefined}));
 }
}else throw Error('Usage: extract DATA ATLAS < ROW.json | grade ROOT ATLAS');
