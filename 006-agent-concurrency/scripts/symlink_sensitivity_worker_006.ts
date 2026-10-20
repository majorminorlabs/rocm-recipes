// CPU-only, on the existing amd64 evooffice host. No agent/model invocation.
import {readFile,mkdir,cp,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const [source,input,output,imageMap]=process.argv.slice(2);
const api=async(p:string)=>import(pathToFileURL(join(source,p)).href);
const {gradingTask}=await api('grading/task.ts');
const {gradeTests}=await api('grading/grader.ts');
const {readTask}=await api('runner/manifest.ts');
const {validPair}=await api('runner/host/images.ts');
const {treeHash}=await api('grading/tree.ts');
const job=JSON.parse(await readFile(input,'utf8'));
const images=JSON.parse(await readFile(imageMap,'utf8'));
const nativeTask=async(task:any)=>{
 const recipe=JSON.parse(await readFile(join(source,'tasks/recipes',task.id+'.json'),'utf8'));
 const name=recipe.dependencyImage.lockFile.split('/').at(-1).replace('.lock.json','');
 return {...task,image:images[name].id,preparation:recipe.preparationCommand};
};
const save=async(p:string,v:any)=>writeFile(p,JSON.stringify(v,null,2)+'\n',{flag:'wx'});
const hash=(b:any)=>createHash('sha256').update(b).digest('hex');
await mkdir(output,{recursive:false});
const checks:any[]=[];
for(const id of ['c09','c10','c11']){
 const task=await gradingTask(id),frozen=await readTask(id);
 if(task.hiddenHash!==job.hidden_hashes[id])throw Error('Hidden tests changed: '+id);
 const native=await nativeTask(task);
 const correct=join(output,'reference-'+id);await treeHash(frozen.directory,correct);
 execFileSync('git',['init','-q'],{cwd:correct});execFileSync('git',['apply','--binary',join(source,'tasks',id,'reference.patch')],{cwd:correct});
 const base=await gradeTests(frozen.directory,native,join(output,id+'-base'));
 const reference=await gradeTests(correct,native,join(output,id+'-reference'));
 checks.push({task:id,base,reference});await save(join(output,'check-'+id+'.json'),checks.at(-1));
 if(!validPair(base,reference))throw Error('Frozen native parent/reference eligibility failed: '+id);
}
const records:any[]=[];
for(const attempt of job.attempts){
 const id=attempt.row.task,task=await gradingTask(id),frozen=await readTask(id);
 const workspace=join(output,attempt.row.run_id,'workspace');await mkdir(workspace,{recursive:true});
 // Reconstruct the saved diff on its exact frozen parent. Generated/untracked
 // agent files are not part of a saved diff; node_modules is explicitly excluded.
 await cp(frozen.directory,workspace,{recursive:true,filter:p=>!p.split('/').includes('node_modules')});
 execFileSync('git',['init','-q'],{cwd:workspace});
 const patch=join(resolve(input,'..'),attempt.patch),bytes=await readFile(patch);
 if(hash(bytes)!==attempt.patch_sha256)throw Error('Saved diff changed');
 if(bytes.length)execFileSync('git',['apply','--binary','--exclude=node_modules/**','--exclude=**/node_modules/**',patch],{cwd:workspace});
 const tests=await gradeTests(workspace,await nativeTask(task),join(output,attempt.row.run_id,'grade'));
 const record={run_id:attempt.row.run_id,task:id,level:attempt.row.level,patch_sha256:attempt.patch_sha256,
  saved_diff_only:true,node_modules_excluded:true,original_end_reason:attempt.row.end_reason,original_tamper:attempt.row.tamper,tests};
 records.push(record);await save(join(output,attempt.row.run_id,'sensitivity.json'),record);
 console.log(JSON.stringify({run_id:record.run_id,tests:tests.status,passed:tests.testsPassed}));
}
await save(join(output,'result.json'),{source_commit:job.source_commit,host:JSON.parse(execFileSync('docker',['info','--format','{{json .}}'],{encoding:'utf8'})).ID,platform:process.arch,checks,records,model_calls:0});
