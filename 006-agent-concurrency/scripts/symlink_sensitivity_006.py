#!/usr/bin/env python3
"""Owner-scoped evooffice saved-diff sensitivity; separate from official exports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
ATLAS=Path('<WORKDIR>/lab/atlas')
PIN='279889b8f42c607344781766503602a8c462f5df'
E=ROOT/'results/analysis/symlink_sensitivity_evooffice'
SSH=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','evooffice']
q=shlex.quote
def run(args,**kw):return subprocess.check_output(args,text=True,**kw).strip()
def ssh(code):return run([*SSH,code])
def save(path,v):path.write_text(json.dumps(v,indent=2)+'\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def upload(path,target):subprocess.run(['scp','-q','-o','StrictHostKeyChecking=yes',str(path),'evooffice:'+target],check=True)

def start():
 E.mkdir(parents=True,exist_ok=False)
 prefix='atlas-006-symlink-20261019-'+uuid.uuid4().hex[:6];remote='<HOME>/'+prefix
 code='''import json,subprocess,platform,shutil
s=lambda a:subprocess.check_output(a,text=True).strip()
c=s(['docker','ps','-aq','--no-trunc']).splitlines()
v={'machine':platform.machine(),'docker':s(['docker','version','--format','{{.Server.Version}}']),'free_bytes':shutil.disk_usage('/').free,
'containers':{x:json.loads(s(['docker','inspect',x]))[0]['State']['Status'] for x in c},
'images':s(['docker','image','ls','-aq','--no-trunc']).splitlines(),'networks':s(['docker','network','ls','-q']).splitlines(),'volumes':s(['docker','volume','ls','-q']).splitlines()}
assert v['machine']=='x86_64' and v['free_bytes']>20*1024**3
print(json.dumps(v))'''
 inventory=json.loads(subprocess.check_output([*SSH,'python3 -'],input=code,text=True));save(E/'inventory.json',inventory)
 save(E/'OWNER.json',dict(prefix=prefix,remote=remote,source_commit=PIN,inventory=inventory))
 ssh(f'test ! -e {q(remote)} && umask 077 && mkdir {q(remote)} && mkdir {q(remote+"/source")} {q(remote+"/home")}')
 upload(E/'OWNER.json',remote+'/OWNER.json')
 raw=E/'input';raw.mkdir();(raw/'patches').mkdir()
 final=json.loads((ROOT/'results/final_analysis.json').read_text());attempts=[]
 data=ROOT/'results/session7/atlas/data'
 with sqlite3.connect('file:'+str(data/'rocm-recipes-006/atlas.db')+'?mode=ro',uri=True) as db:
  for failure in final['grader_infra']:
   if failure['kind']!='symlink_snapshot':continue
   id=failure['run_id'];row=next(r for r in json.loads((ROOT/f'results/atlas/scored/final/{failure["level"]}/runs.json').read_text())['rows'] if r['run_id']==id)
   diff=db.execute('SELECT diff_path FROM runs WHERE run_id=?',(id,)).fetchone()[0]
   source=data/diff.split('/atlas/data/',1)[1];dest=raw/'patches'/(id+'.patch');shutil.copyfile(source,dest)
   attempts.append(dict(row=row,patch='patches/'+dest.name,patch_sha256=digest(dest)))
 assert len(attempts)==13
 js="import{gradingTask}from'./grading/task.ts';const o={};for(const t of ['c09','c10','c11'])o[t]=(await gradingTask(t)).hiddenHash;console.log(JSON.stringify(o));"
 hidden=json.loads(run(['node','--input-type=module','-e',js],cwd=ATLAS))
 save(raw/'attempts.json',dict(source_commit=PIN,hidden_hashes=hidden,attempts=attempts))
 selected=['config','grading','runner','proxy','tasking','tasks/c09','tasks/c10','tasks/c11','tasks/FROZEN.json','tasks/recipes']
 with (E/'source.tar.gz').open('wb') as f:subprocess.run(['git','-C',str(ATLAS),'archive','--format=tar.gz',PIN,*selected],stdout=f,check=True)
 upload(E/'source.tar.gz',remote+'/source.tar.gz');upload(ROOT/'scripts/symlink_sensitivity_worker_006.ts',remote+'/worker.ts')
 subprocess.run(['rsync','-a','-e','ssh -o StrictHostKeyChecking=yes',str(raw)+'/',f'evooffice:{remote}/input/'],check=True)
 ssh(f'tar -xzf {q(remote+"/source.tar.gz")} -C {q(remote+"/source")}')
 # umask 077 protects the owner folder; task hashing still needs frozen modes.
 mode_fix=f'''import pathlib,tarfile
root=pathlib.Path({remote!r})/'source'
for p in root.rglob('*'):
 if p.is_dir() and not p.is_symlink():p.chmod(0o755)
with tarfile.open(pathlib.Path({remote!r})/'source.tar.gz') as t:
 for m in t.getmembers():
  if m.isfile():(root/m.name).chmod(0o755 if m.mode&0o111 else 0o644)
'''
 subprocess.run([*SSH,'python3 -'],input=mode_fix,text=True,check=True)
 context=E/'contexts'
 for dependency in ('tokenx','tokenx2'):
  subprocess.run(['python3',str(ATLAS/'runner/host/dependencies.py'),'--source',str(ATLAS),'--output',str(context),'--architecture','amd64',dependency],check=True,stdout=(E/('context-'+dependency+'.log')).open('w'))
 client=E/'docker-client';(client/'cli-plugins').mkdir(parents=True);(client/'cli-plugins/docker-buildx').symlink_to('<HOME>/.docker/cli-plugins/docker-buildx')
 docker=['docker','--config',str(client),'--host','ssh://evooffice']
 labels={'atlas.host-build':prefix};base=json.loads(run(['node','--input-type=module','-e',"import{config}from'./config/atlas.config.ts';console.log(JSON.stringify(config.images));"],cwd=ATLAS))
 target={
  'base':dict(context=str(ATLAS/'images'),dockerfile='base.Dockerfile',contexts={'atlas-node':'docker-image://'+base['base']['upstream']},tags=[prefix+'-base:v1'],platforms=['linux/amd64'],labels=labels,args=dict(NODE_VERSION=base['base']['nodeVersion'],NPM_VERSION=base['base']['npmVersion'])),
  'opencode':dict(context=str(ATLAS/'images'),dockerfile='opencode.Dockerfile',contexts={'atlas-base':'target:base'},tags=[prefix+'-opencode:v1'],platforms=['linux/amd64'],labels=labels,args=dict(OPENCODE_VERSION=base['opencode']['version'],RELEASE_URL=base['opencode']['releaseUrl'],ARM64_FILE=base['opencode']['assets']['arm64']['file'],ARM64_SHA256=base['opencode']['assets']['arm64']['sha256'],AMD64_FILE=base['opencode']['assets']['amd64']['file'],AMD64_SHA256=base['opencode']['assets']['amd64']['sha256'])),
  'tokenx':dict(context=str(context/'tokenx'),dockerfile='Dockerfile',contexts={'atlas-parent':'target:opencode'},tags=[prefix+'-tokenx:v1'],platforms=['linux/amd64'],labels=labels)}
 target['tokenx2']={**target['tokenx'],'context':str(context/'tokenx2'),'tags':[prefix+'-tokenx2:v1']}
 save(E/'bake.json',dict(target=target))
 launch()

def launch():
 if (E/'process.json').exists():raise RuntimeError('A worker was already dispatched; inspect retained run before any new grading')
 owner=json.loads((E/'OWNER.json').read_text());prefix=owner['prefix'];remote=owner['remote'];inventory=owner['inventory']
 target=json.loads((E/'bake.json').read_text())['target']
 docker=['docker','--config',str(E/'docker-client'),'--host','ssh://evooffice']
 with (E/'build-allowed.log').open('w') as log:
  subprocess.run([*docker,'buildx','bake','-f',str(E/'bake.json'),*target,'--allow=fs.read='+str(ATLAS/'images'),'--allow=fs.read='+str(E/'contexts'),'--load','--progress','plain'],stdout=log,stderr=subprocess.STDOUT,check=True)
 images={}
 for name,t in target.items():
  item=json.loads(run([*docker,'image','inspect',t['tags'][0]]))[0]
  assert item['Id'] not in inventory['images'] and item['Config']['Labels']['atlas.host-build']==prefix and item['Architecture']=='amd64'
  images[name]=dict(tag=t['tags'][0],id=item['Id'])
 save(E/'images.json',images);upload(E/'images.json',remote+'/images.json')
 name=prefix+'-node-export'
 ssh(f'docker create --name {name} --label atlas.host-build={prefix} --network none --entrypoint /bin/true {images["base"]["id"]} >/dev/null && docker cp {name}:/usr/local/bin/node {remote}/node && docker rm {name} >/dev/null')
 command=f'cd {remote}/source\nexport HOME={remote}/home\n{remote}/node {remote}/worker.ts {remote}/source {remote}/input/attempts.json {remote}/grades {remote}/images.json'
 script='#!/bin/bash\nset -euo pipefail\ntrap \'echo $? > '+remote+'/exit-code\' EXIT\n'+command+'\n'
 (E/'run.sh').write_text(script);upload(E/'run.sh',remote+'/run.sh')
 pid=ssh(f'nohup bash {remote}/run.sh > {remote}/worker.log 2>&1 < /dev/null & echo $!')
 save(E/'process.json',dict(pid=int(pid),command=command,model_calls=0));print(json.dumps(dict(remote=remote,pid=int(pid))))

def collect():
 owner=json.loads((E/'OWNER.json').read_text());remote=owner['remote']
 code=ssh(f'if test -f {remote}/exit-code; then cat {remote}/exit-code; else echo running; fi')
 print(code)
 if code=='running':print(ssh(f'tail -n 4 {remote}/worker.log'));return
 subprocess.run(['rsync','-a','-e','ssh -o StrictHostKeyChecking=yes',f'evooffice:{remote}/grades/',str(E/'grades')+'/'],check=True)
 upload_target=E/'worker.log';upload_target.write_text(ssh(f'cat {remote}/worker.log')+'\n')
 save(E/'exit.json',dict(exit_code=int(code)))
 if int(code):raise RuntimeError('Sensitivity worker failed; retained logs')

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','launch','collect']);args=p.parse_args()
 {'start':start,'launch':launch,'collect':collect}[args.action]()
