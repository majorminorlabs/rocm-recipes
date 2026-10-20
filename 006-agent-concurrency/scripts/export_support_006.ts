// Infra rows have no usable evidence. Do not invoke the native grader on them.
import {isDeepStrictEqual} from 'node:util';
import {lstat,realpath,open,link,rename,unlink} from 'node:fs/promises';
import {resolve,join,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';

// Native saveJson pretty-prints cached grades. Repeated streaming evidence can
// fit the reader's bound as compact JSON but exceed it after indentation.
// Fix the producer representation immediately after gradeRun, before a retry
// revisits the cache. Never raise the reader's limit or discard evidence.
export async function compactGrade(record:any, atlas:string, retainedDirectory=record.directory) {
 if(typeof retainedDirectory!=='string')return null;
 const name=record.status==='complete'?'grade.json':'grade-pending.json';
 const data=await realpath(resolve('data')),directory=await realpath(retainedDirectory);
 if(!directory.startsWith(join(data,'grading')+sep))throw Error('Grade destination must be inside data/grading');
 const path=join(directory,name),info=await lstat(path),max=32*1024*1024;
 if(!info.isFile()||info.isSymbolicLink())throw Error('Grade destination must be a regular file');
 if(info.size<=max)return null;
 const {redact}=await import(pathToFileURL(resolve(atlas,'grading/redact.ts')).href);
 const value=redact(record),body=JSON.stringify(value),bytes=Buffer.byteLength(body);
 if(bytes>max)throw Error(`Compact grade still exceeds strict artifact bound: ${bytes} > ${max}: ${path}`);
 const temporary=path+'.'+randomUUID()+'.tmp',file=await open(temporary,'wx',0o600);
 try{await file.writeFile(body);await file.sync();}finally{await file.close();}
 try{
  // Preserve the original bytes; an existing backup is never overwritten.
  await link(path,path+'.pretty-original');
  await rename(temporary,path);
 }finally{await unlink(temporary).catch((e:any)=>{if(e.code!=='ENOENT')throw e;});}
 return {path,original_bytes:info.size,compact_bytes:bytes};
}
export function infraGrade(row:any, reason='interrupted/infra execution') {
 return {runId:row.run_id,executionRow:{...row,end_reason:'infra'},status:'complete',category:'infra_error',
  flags:[reason],tests:{testsPassed:null},protection:{tamper:null},claim:null,
  evidence:{raw:[],tokens:{input:null,output:null,cached:null},inferenceS:null,toolCalls:[],tokenSource:'unavailable'},
  cost:{costUsd:row.cost_usd??null}};
}
export function historicalGrade(entry:any, row:any, meta:any) {
 if(!isDeepStrictEqual({...entry.row},{...row}))throw Error('Historical DB row changed: '+row.run_id);
 if(!entry.grade)return infraGrade(row);
 if(meta?.status!=='complete'||meta.fingerprint!==entry.grade.fingerprint||entry.grade.runId!==row.run_id)
  throw Error('Historical grade is not bound to the restored DB: '+row.run_id);
 return entry.grade;
}
