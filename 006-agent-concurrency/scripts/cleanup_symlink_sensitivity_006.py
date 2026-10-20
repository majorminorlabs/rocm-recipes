#!/usr/bin/env python3
"""Remove only this sensitivity's recorded resources, after committed evidence."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'results/analysis/symlink_sensitivity_evooffice'
owner=json.loads((E/'OWNER.json').read_text());prefix=owner['prefix'];remote=owner['remote']
assert re.fullmatch(r'atlas-006-symlink-20261019-[0-9a-f]{6}',prefix) and remote=='<HOME>/'+prefix
archive=E/'evidence.tar.gz';receipt=json.loads((E/'archive.json').read_text())
assert hashlib.sha256(archive.read_bytes()).hexdigest()==receipt['sha256']
relative=str(archive.relative_to(ROOT))
assert subprocess.check_output(['git','hash-object',str(archive)],text=True).strip()==subprocess.check_output(['git','rev-parse','HEAD:'+relative],cwd=ROOT,text=True).strip()
extra=E/receipt['v11_evidence']['file']
assert hashlib.sha256(extra.read_bytes()).hexdigest()==receipt['v11_evidence']['sha256']
assert subprocess.check_output(['git','hash-object',str(extra)],text=True).strip()==subprocess.check_output(['git','rev-parse','HEAD:'+str(extra.relative_to(ROOT))],cwd=ROOT,text=True).strip()
code='''import pathlib,subprocess,json,hashlib,shutil
owner=INPUT
root=pathlib.Path(owner['remote']);assert not root.is_symlink()
assert json.loads((root/'OWNER.json').read_text())==owner
assert hashlib.sha256((root/'evidence.tar.gz').read_bytes()).hexdigest()==ARCHIVE_SHA
assert hashlib.sha256((root/'v11-evidence.tar.gz').read_bytes()).hexdigest()==V11_SHA
images=json.loads((root/'images.json').read_text());removed=[]
for key in ['tokenx2','tokenx','opencode','base']:
 record=images[key];info=json.loads(subprocess.check_output(['docker','image','inspect',record['tag']],text=True))[0]
 assert info['Id']==record['id'] and info['Id'] not in owner['inventory']['images'] and info['Config']['Labels']['atlas.host-build']==owner['prefix']
 subprocess.run(['docker','image','rm',record['tag']],check=True,stdout=subprocess.DEVNULL);removed.append(record)
s=lambda a:subprocess.check_output(a,text=True).strip()
c=s(['docker','ps','-aq','--no-trunc']).splitlines()
after={'containers':{x:json.loads(s(['docker','inspect',x]))[0]['State']['Status'] for x in c},'images':s(['docker','image','ls','-aq','--no-trunc']).splitlines(),'networks':s(['docker','network','ls','-q']).splitlines(),'volumes':s(['docker','volume','ls','-q']).splitlines()}
for id,state in owner['inventory']['containers'].items():assert after['containers'].get(id)==state
for kind in ['images','networks','volumes']:assert set(owner['inventory'][kind])<=set(after[kind])
assert not any(r['id'] in after['images'] for r in removed)
shutil.rmtree(root);assert not root.exists()
print(json.dumps({'removed_images':removed,'remote_folder_absent':True,'baseline_resources_preserved':True,'after':after,'pruned':False,'shared_cache_pruned':False,'build_cache_retained':True}))
'''.replace('INPUT',repr(owner)).replace('ARCHIVE_SHA',repr(receipt['sha256'])).replace('V11_SHA',repr(receipt['v11_evidence']['sha256']))
result=subprocess.check_output(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','evooffice','python3 -'],input=code,text=True)
(E/'cleanup.json').write_text(json.dumps(json.loads(result),indent=2)+'\n');print('Owned images/folder removed; pre-existing containers, images, networks and volumes preserved; no prune.')
