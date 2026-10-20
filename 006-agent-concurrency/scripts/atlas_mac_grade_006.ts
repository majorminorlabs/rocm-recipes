// Split only missing-STATUS grading: native tests on build host, pinned MLX claim on Mac.
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {resolve,join,dirname} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const pin='279889b8f42c607344781766503602a8c462f5df';
const sha=(v:string)=>createHash('sha256').update(v).digest('hex');
const read=async(p:string)=>JSON.parse(await readFile(p,'utf8'));
const api=async(p:string)=>import(pathToFileURL(resolve(p)).href);
async function cpAudit(call:string,out:string){await writeFile(join(out,'audit.json'),await readFile(join(call,'audit.json')),{flag:'wx'});}
const exists=async(p:string)=>{try{await access(p);return true;}catch{return false;}};
function checkPin(){if(execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin)throw Error('Wrong ATLAS pin');}

export async function missingGrade(runId:string,level:string,db:string,study:string,allowPending=false,results=join(study,'results'),gradingKey=runId):Promise<any|null>{
 checkPin();
 const {Store}=await api('runner/store.ts'),{readEvidence,artifactText}=await api('grading/evidence.ts');
 const {gradeTests}=await api('grading/grader.ts'),{gradingTask}=await api('grading/task.ts');
 const {treeHash}=await api('grading/tree.ts'),{captureProtection,compareProtection}=await api('grading/tamper.ts');
 const {recheckRuntime}=await api('runner/host/images.ts');
 const {readPrices,computeCost}=await api('grading/cost.ts'),{observedAgentWork,secondaryFlags,categorize}=await api('grading/taxonomy.ts');
 const {taskProvenance}=await api('grading/cutoff.ts'),{redact}=await api('grading/redact.ts');
 const store=new Store(db);let row:any,manifest:any;
 try{
  // Use the normal ATLAS owner lock while reading finished execution identity.
  const owner=store.acquire();
  try{
   row=store.row(runId);if(row.state!=='finished')throw Error('Missing-STATUS handoff needs finished execution');
   manifest=JSON.parse(store.db.prepare('SELECT m.manifest_json FROM manifests m JOIN manifest_runs mr ON mr.manifest_id=m.id WHERE mr.run_id=?').get(runId).manifest_json);
  }finally{store.release(owner);}
 }finally{store.close();}
 const text=await artifactText(row.trace_path),execution=JSON.parse(text);
 const workspace=join(dirname(row.trace_path),'workspace'),workspaceHash=await treeHash(workspace);
 if(execution.hostImage)await recheckRuntime(execution.hostImage,row.task_id);
 const pending=join(results,'grading/pending',gradingKey),requestPath=join(pending,'request.json');
 let request:any;
 if(await exists(requestPath)){
  request=await read(requestPath);
  if(request.trace_sha256!==sha(text)||request.workspace_sha256!==workspaceHash||request.level!==level)throw Error('Missing-STATUS inputs changed; preserve original handoff');
  if(request.native_tests_sha256!==sha(await readFile(join(pending,'native-tests/tests.json'),'utf8')))throw Error('Native test handoff changed');
 }else{
  await mkdir(pending,{recursive:true});
  let task=await gradingTask(row.task_id);
  if(execution.hostImage){await recheckRuntime(execution.hostImage,row.task_id);task={...task,image:execution.hostImage.entry.image,preparation:execution.hostImage.entry.preparation};}
  const tests=await gradeTests(workspace,task,join(pending,'native-tests'));
  let protection=null,baselineSource='unavailable';
  try{
   const before=await read(join(dirname(row.trace_path),'protection-before.json'));
   protection=compareProtection(before,await captureProtection(workspace,row.task_id));baselineSource='captured_before_agent';
  }catch{ /* An unavailable verdict remains infra, never inferred clean. */ }
  const evidence=await readEvidence(row.backend,row.harness,execution),prices=await readPrices();
  const cost=computeCost({backend:row.backend,tokens:evidence.tokens,tokenSource:evidence.tokenSource,wallS:row.wall_s,price:prices[row.model]??null,local:manifest.localCost??null,subscription:manifest.subscriptionCost??null,noRequests:evidence.noRequests});
  const work=observedAgentWork(await artifactText(row.diff_path),await artifactText(execution.result.stdoutPath));
  const record={runId,directory:pending,execution,executionRow:row,tests,protection,baselineSource,cost,evidence,
   flags:secondaryFlags(evidence.finalMessage,evidence.toolCalls,5),taskProvenance:await taskProvenance(row.task_id,JSON.parse(row.config_json)),
   fixture:manifest.study.dryRun,status:'audit_pending',category:null,claim:null};
  request={version:1,atlas_commit:pin,run_id:runId,level,trace_sha256:sha(text),workspace_sha256:workspaceHash,native_tests_sha256:sha(await readFile(join(pending,'native-tests/tests.json'),'utf8')),work,record};
  await writeFile(requestPath,JSON.stringify(redact(request),null,2)+'\n',{flag:'wx'});
 }
 if(request.record.tests.testsPassed===null||!request.record.protection){
  request.record.category='infra_error';request.record.status='complete';return request.record;
 }
 const responsePath=join(results,'grading/returned',gradingKey,'response.json');
 if(!await exists(responsePath)){
  if(!allowPending)return null;
  const record=structuredClone(request.record);
  record.grading_pending=true;
  record.category=categorize({infra:record.tests.testsPassed===null||!record.protection,endReason:row.end_reason,tamper:record.protection?.tamper??false,testsPassed:record.tests.testsPassed,claim:'none'});
  return record;
 }
 const result=await read(responsePath);
 if(result.run_id!==runId||result.request_sha256!==sha(await readFile(requestPath,'utf8'))||result.atlas_commit!==pin||result.claim?.audited!==true||result.claim?.source!=='llm_fallback'||!['done','incomplete','none'].includes(result.claim?.claim))throw Error('Returned Mac grade is unbound/unaudited');
 const auditPath=join(dirname(responsePath),'audit.json');
 const audit=await read(auditPath);
 if(audit.accepted!==true||audit.expected!==result.claim.claim||audit.reported!==result.claim.claim||!audit.reviewer||!audit.reason)throw Error('Returned semantic audit missing or disagrees');
 // A returned verdict cannot replace native tests, tamper or execution measurements.
 const record=request.record;
 record.claim=result.claim;record.status='complete';
 record.category=categorize({infra:(row.end_reason==='infra'&&!request.work)||record.tests.testsPassed===null||!record.protection,
  endReason:row.end_reason,tamper:record.protection?.tamper??false,testsPassed:record.tests.testsPassed,claim:result.claim.claim});
 if(result.category!==record.category)throw Error('Mac and native-host taxonomy disagree');
 record.mac_grade={request_sha256:result.request_sha256,response:responsePath};
 return record;
}

async function main(){
 checkPin();
 const [mode,requestPath,out,claim,reviewer,reason]=process.argv.slice(2);
 if(!['classify','audit'].includes(mode)||!requestPath||!out)throw Error('Usage: classify REQUEST OUT | audit REQUEST OUT <done|incomplete|none> REVIEWER REASON');
 if(process.platform!=='darwin')throw Error('MLX claim grading is Mac-only');
 const request=await read(requestPath),requestHash=sha(await readFile(requestPath,'utf8'));
 if(request.atlas_commit!==pin)throw Error('Handoff pin mismatch');
 if(sha(await readFile(join(dirname(requestPath),'native-tests/tests.json'),'utf8'))!==request.native_tests_sha256)throw Error('Synced native test evidence changed');
 const {classifyClaim,auditClaim}=await api('grading/claim.ts');
 if(mode==='classify'){
  // Exclusive reservation: uncertain calls are never automatically replayed.
  await mkdir(out,{recursive:false});
  await writeFile(join(out,'reservation.json'),JSON.stringify({run_id:request.run_id,request_sha256:requestHash,automatic_retry:false})+'\n',{flag:'wx'});
  const {startMlx}=await api('local/server.ts');
  const server=await startMlx(join(out,'mlx-classifier.log'));
  try{
   const result=await classifyClaim(request.record.evidence.finalMessage,join(out,'classifier'));
   await writeFile(join(out,'claim.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  }finally{await server.stop();}
  console.log('Classifier retained; explicit semantic audit required before returning a grade.');
 }else{
  if(await exists(join(out,'response.json')))throw Error('Audit response already exists');
  const reservation=await read(join(out,'reservation.json'));
  if(reservation.request_sha256!==requestHash||reservation.run_id!==request.run_id)throw Error('Audit request changed');
  const result=await auditClaim(await read(join(out,'claim.json')),claim,reviewer,reason);
  await cpAudit(result.callDirectory, out);
  const {categorize}=await api('grading/taxonomy.ts');
  const r=request.record;
  const category=categorize({infra:(r.executionRow.end_reason==='infra'&&!request.work)||r.tests.testsPassed===null||!r.protection,endReason:r.executionRow.end_reason,tamper:r.protection?.tamper??false,testsPassed:r.tests.testsPassed,claim:result.claim});
  await writeFile(join(out,'response.json'),JSON.stringify({atlas_commit:pin,run_id:request.run_id,request_sha256:requestHash,claim:result,category},null,2)+'\n',{flag:'wx'});
  console.log('Audited Mac claim grade ready to return; native verdicts remain on the execution host.');
 }
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))await main();
