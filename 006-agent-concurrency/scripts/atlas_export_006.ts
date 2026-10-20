// Run from the pinned ATLAS checkout. Uses its grader/proxy evidence, no model calls.
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {resolve,dirname,join,basename} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {missingGrade} from './atlas_mac_grade_006.ts';
import {gunzipSync} from 'node:zlib';
import {infraGrade,historicalGrade,compactGrade} from './export_support_006.ts';
const root=process.cwd(), study=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const rehearsal=process.env.REHEARSAL==='1';
const results=join(study,'results',...(rehearsal?['rehearsal']:[])), context=rehearsal?results:study;
const probeDir=rehearsal?'data/rocm-recipes-006-rehearsal-probe':'data/rocm-recipes-006-probe';
const read=async (p:string)=>JSON.parse(await readFile(p,'utf8'));
const importAtlas=async(p:string)=>import(pathToFileURL(resolve(root,p)).href);
const pin='279889b8f42c607344781766503602a8c462f5df';
if(execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin)throw Error('Wrong ATLAS pin');
const [manifestPath,db,mode]=process.argv.slice(2);
if(mode!==undefined&&mode!=='--final')throw Error('Only --final is supported after manifest/db');
if(manifestPath==='--choose'){
 const candidates=[];
 for(const engine of ['vllm','sglang']){
  try{
   let failed=false;try{await access(join(context,'logs','probe_'+engine+'.failure'));failed=true;}catch{}
   if(failed)throw Error('engine startup/stage failure; see probe failure log');
   const reports=await Promise.all(['smoke','c8'].map(stage=>read(`${probeDir}/live/${engine}-${stage}/runs.json`)));
   const rows=reports.flatMap(r=>r.rows);
   if(!reports[0].rows.some((r:any)=>r.tool_calls>0&&r.reasoning_observed))throw Error('smoke lacks parsed tools/reasoning');
   if(!reports[0].rows.some((r:any)=>r.cache_reporting_verified===true))throw Error('smoke lacks nonzero proxy cached tokens after the first request');
   if(rows.some((r:any)=>r.category==='infra_error'||r.tool_parse_error))throw Error('tool/proxy/infra failure');
   const group=reports[1].rows,solved=group.filter((r:any)=>r.solved_by_tests??(r.category==='solved')).length;
   if(group.length!==8||new Set(group.map((r:any)=>r.task)).size!==8||!['c13','c18','c45'].every(id=>group.some((r:any)=>r.task===id)))throw Error('R1 requires eight distinct c8 tasks including C13/C18/C45');
   const seconds=(Math.max(...group.map((r:any)=>Date.parse(r.ended_at)))-Math.min(...group.map((r:any)=>Date.parse(r.started_at))))/1000;
   const output=group.every((r:any)=>r.tokens_out!==null)?group.reduce((n:number,r:any)=>n+r.tokens_out,0):null;
   candidates.push({engine,eligible:true,solved,pending_mac_grades:group.filter((r:any)=>r.grading_pending).length,successful_tasks_per_hour:solved*3600/seconds,output_tok_per_s:output===null?null:output/seconds});
  }catch(e){candidates.push({engine,eligible:false,error:String(e)});}
 }
 const eligible=candidates.filter(r=>r.eligible);
 const forced=rehearsal&&eligible.length===2&&eligible[0].solved===eligible[1].solved;
 const forced_reason=forced?'CPU rehearsal: equal solved counts; force SGLang to exercise Phase 3b':null;
 if(!eligible.length)throw Error('Neither engine passes probe: '+JSON.stringify(candidates));
 if(!forced&&eligible.length===2&&eligible[0].solved===eligible[1].solved&&eligible.some(r=>r.output_tok_per_s===null))throw Error('Tie cannot be resolved: missing output tokens');
 eligible.sort((a,b)=>a.solved===b.solved?(b.output_tok_per_s??0)-(a.output_tok_per_s??0):(b.successful_tasks_per_hour??0)-(a.successful_tasks_per_hour??0));
 if(!forced&&eligible.length===2&&eligible[0].solved===eligible[1].solved&&eligible[0].output_tok_per_s===eligible[1].output_tok_per_s)throw Error('Exact tie: record data and request engine decision');
 const engine=forced?'sglang':eligible[0].engine;
 await mkdir(dirname(db),{recursive:true});
 await writeFile(db,'# Engine choice\n\nPicked: '+engine+'\n\n'+(forced_reason??'')+'\n\n```json\n'+JSON.stringify(candidates,null,2)+'\n```\n\nReporting-only flags: vLLM `--enable-prompt-tokens-details`; SGLang `--enable-cache-report` (identical for FCFS and LPM). These expose cached-token usage without changing tuning. Smoke requires nonzero proxy cached tokens on at least one request after the first.\n\nProbe only, excluded from scores. Exactly eight tasks at c8, including C13/C18/C45; no c1 probe stage. Output tok/s = total output / level elapsed seconds.\n');
 await writeFile(db.replace(/\.md$/,'.json'),JSON.stringify({engine,candidates,atlas_commit:pin,rehearsal,forced,forced_reason},null,2)+'\n');
 console.log('Picked '+engine);process.exit(0);
}
if(!manifestPath||!db)throw Error('Usage: atlas_export_006.ts <manifest> <db> | --choose <notes.md>');
const {loadManifest}=await importAtlas('runner/manifest.ts');
const {gradeRun}=await importAtlas('grading/service.ts');
const {parseStatus}=await importAtlas('grading/claim.ts');
const {Store}=await importAtlas('runner/store.ts');
const {readEvidence,artifactText}=await importAtlas('grading/evidence.ts');
const loaded=await loadManifest(manifestPath),m=loaded.manifest,fixture=m.study.dryRun;
if(rehearsal!==m.id.includes('-rehearsal-'))throw Error('Manifest/rehearsal mode mismatch');
if(rehearsal&&!fixture)throw Error('Rehearsal must remain unscored');
const probe=fixture&&(!rehearsal||m.id.includes('-probe-'));
let session4:any=null, history:any=null;
if(m.id.includes('-session4-')){
 execFileSync('python3',[join(study,'scripts/session4_006.py'),'verify','--root',study,'--atlas',root]);
 session4=await read(join(dirname(resolve(manifestPath)),'session4.json'));
 history=JSON.parse(gunzipSync(await readFile(session4.history)).toString('utf8'));
}
const carried=session4&&m.study.level==='c1'?history.entries:[];
const extra=[];
if(session4){
 for(const n of [1,2]){
  const path=join(dirname(resolve(manifestPath)),m.study.level+'-retry'+n+'.json');
  let exists=false;try{await access(path);exists=true;}catch{}
  if(exists)extra.push(...(await loadManifest(path)).runs);
 }
}
const specs=[...loaded.runs,...extra,...carried.map((e:any)=>({runId:e.row.run_id}))];
const rows=[],pending=[],c1Usage=[];let missingCount=0,unfinished=0;
for(const spec of specs){
 const store=new Store(db);let missing=false,alreadyGraded=false,g:any=null;
 try{
  const r=store.row(spec.runId);
  if(!r||r.state!=='finished'){unfinished++;continue;}
  const prior=store.db.prepare('SELECT * FROM grades WHERE run_id=?').get(spec.runId);
  const retained=carried.find((e:any)=>e.row.run_id===spec.runId);
  if(retained)g=historicalGrade(retained,r,prior);
  else if(r.end_reason==='infra'||!r.trace_path)g=infraGrade(r);
  else{
   const execution=JSON.parse(await artifactText(r.trace_path));
   if(execution.result?.stdoutPath===null||execution.proxy_log===null)g=infraGrade(r,'null evidence path');
   else{
    const evidence=await readEvidence(r.backend,r.harness,execution);
    missing=r.end_reason==='completed'&&!parseStatus(evidence.finalMessage);
    alreadyGraded=prior?.status==='complete';
   }
  }
 }finally{store.close();}
 if(missing)missingCount++;
 const gradingKey=probe?basename(db,'.db')+'__'+spec.runId:spec.runId;
 if(!g){
  if(missing&&!alreadyGraded)g=await missingGrade(spec.runId,m.study.level,db,study,true,results,gradingKey);
  else{
   g=await gradeRun(spec.runId,{db});
   const compacted=await compactGrade(g,root);
   if(compacted)console.log('Compacted cached grade: '+JSON.stringify(compacted));
  }
 }
 if(g.grading_pending||g.status!=='complete')pending.push(spec.runId);
 const r=g.executionRow, events=g.evidence.raw as any[];
 const limits=JSON.parse(r.limits_json??'null'),totals=limits?.totals;
 const responses=events.filter(e=>e.event==='response');
 if(m.study.level==='c1'&&!probe)c1Usage.push(...responses.map(e=>({event:'response',run_id:g.runId,request_id:e.request_id,tokens_cached:e.tokens_cached??null})));
 // Request order, rather than response completion order, defines the first call.
 const requestIds=[...new Set(events.filter(e=>e.event==='request').map(e=>e.request_id))];
 const laterRequests=new Set(requestIds.slice(1));
 const cachedAfterFirst=responses.filter(e=>laterRequests.has(e.request_id)&&e.token_source==='proxy'&&Number.isSafeInteger(e.tokens_cached)&&e.tokens_cached>0);
 const payloads=responses.flatMap(e=>Array.isArray(e.response)?e.response:[e.response]);
 const reasoning=payloads.some(e=>e?.choices?.some((c:any)=>Boolean(c.message?.reasoning_content||c.delta?.reasoning_content||c.message?.reasoning||c.delta?.reasoning)));
 const rawToolText=payloads.some(e=>e?.choices?.some((c:any)=>/<tool_call>|<function=/.test(c.message?.content??c.delta?.content??'')));
 rows.push({run_id:g.runId,task:r.task_id,config:r.config_id,model:r.model,harness_version:r.harness_version,
  level:m.study.level,evidence_available:g.category!=='infra_error',study_session:carried.some((e:any)=>e.row.run_id===g.runId)?3:session4?4:null,evidence_path:g.category==='infra_error'?null:r.trace_path,grading_key:gradingKey,grading_pending:pending.includes(g.runId),solved_by_tests:g.tests.testsPassed===true&&g.protection?.tamper===false&&g.category!=='infra_error',missing_status:missing,claim_source:g.claim?.source??null,mac_grade:g.mac_grade??null,attempt:r.attempt,retry_of:r.retry_of,started_at:r.started_at,ended_at:r.ended_at,wall_s:r.wall_s,
  inference_s:g.evidence.inferenceS,tokens_in:g.evidence.tokens.input,tokens_out:g.evidence.tokens.output,tokens_cached:g.evidence.tokens.cached,
  token_accounting:totals?.tokenAccounting??null,tokens_uncached_in:totals?.tokensUncachedIn??null,tokens_cumulative:totals?.tokensCumulative??null,
  tokens_counted:totals?.tokensCounted??null,soft_token_limit:totals?.softTokenLimit??null,token_overshoot:totals?.tokenOvershoot??null,
  cap_at:limits?.cap?.at??null,agent_stopped_at:limits?.agentStoppedAt??null,cap_stop_latency_ms:limits?.stopLatencyMs??null,
  refusal_count:g.category==='infra_error'?null:events.filter(e=>e.event==='blocked').length,turns:g.category==='infra_error'?null:events.filter(e=>e.event==='request').length,tool_calls:g.category==='infra_error'?null:g.evidence.toolCalls.length,
  reasoning_observed:reasoning,tool_parse_error:rawToolText,
  cache_reporting_verified:cachedAfterFirst.length>0,proxy_request_count:requestIds.length,cached_requests_after_first:cachedAfterFirst.map(e=>e.request_id),
  tests_passed:g.tests.testsPassed,tamper:g.protection?.tamper??null,claim:g.claim?.claim??null,category:g.category,flags:g.flags,end_reason:r.end_reason,
  cost_basis:'local',cost_usd:g.cost.costUsd,token_source:g.evidence.tokenSource,
  training_cutoff:g.taskProvenance?.cutoff.trainingCutoff??null,cutoff_status:g.taskProvenance?.cutoff.status??'unknown',
  rehearsal,fixture,scored:!fixture,model_latency_s:g.category==='infra_error'?null:responses.map(e=>e.inference_s),
  ttft_s:null}); // Pinned proxy records response headers, not first generated token: never relabel as TTFT.
}
const stage=probe?basename(db,'.db'):m.study.level;
if(c1Usage.length){await mkdir(join(results,'live'),{recursive:true});await writeFile(join(results,'live/c1_proxy_usage.jsonl'),c1Usage.map(e=>JSON.stringify(e)).join('\n')+'\n');}
const counts=join(results,'grading/counts');await mkdir(counts,{recursive:true});
await writeFile(join(counts,stage+'.json'),JSON.stringify({level:m.study.level,stage,missing_status_runs:missingCount,pending_mac_grades:pending.length,run_ids:pending},null,2)+'\n');
if((pending.length||unfinished)&&mode==='--final'){console.error('Final export blocked: pending Mac grades '+pending.join(', '));process.exit(3);}
if(pending.length)console.log('Deferred Mac grades (queue continues): '+pending.length);
const out=resolve(dirname(db),mode==='--final'?'export':'live',stage);await mkdir(out,{recursive:true});
const report=JSON.stringify({complete:pending.length===0&&unfinished===0,execution_complete:unfinished===0,matched_tasks:session4?.matched_tasks??null,pending_mac_grades:pending.length,atlas_commit:pin,rehearsal,scored:!fixture,rows,infra_attempts:[]},null,2)+'\n';
await writeFile(join(out,'runs.json'),report);
const mirror=join(results,'atlas',probe?'probe':rehearsal?'main':'scored',mode==='--final'?'final':'live',stage);await mkdir(mirror,{recursive:true});
await writeFile(join(mirror,'runs.json'),report);
if(m.id.endsWith('-smoke')&&!rows.some(r=>r.tool_calls>0&&r.reasoning_observed&&!r.tool_parse_error))throw Error('Smoke failed parsed tool/reasoning check');
if(m.id.endsWith('-smoke')&&!rows.some(r=>r.cache_reporting_verified))throw Error('Smoke failed: no nonzero proxy cached tokens after the first request');
if(!probe){
 const {readdir}=await import('node:fs/promises');
 const dir=resolve(dirname(db),mode==='--final'?'export':'live'),paths=(await readdir(dir)).filter(n=>/^c(1|4|8|16|32)$/.test(n)).sort().map(n=>join(dir,n,'runs.json'));
 const {globSync}=await import('node:fs');
 const samples=globSync(join(results,'raw/c*/samples.jsonl'));
 execFileSync('python3',[join(study,'scripts/summarize_006.py'),...paths,'--output-dir',join(results,...(mode==='--final'?[]:['live'])),...(mode==='--final'?[]:['--live']),...(rehearsal?['--allow-fixtures']:[]),...(samples.length?['--samples',...samples]:[])],{stdio:'inherit'});
}
console.log('Exported '+out);
