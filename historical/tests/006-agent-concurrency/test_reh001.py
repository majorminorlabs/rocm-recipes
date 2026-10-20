"""REH-001: environment pinning, strict verification and a narrowly scoped grant."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import rehearse_006 as driver

ENGINE_APT='5:29.8.2-1~ubuntu.24.04~noble'
BUILDX_APT='0.37.1-1~ubuntu.24.04~noble'
BUILDX='github.com/docker/buildx v0.37.1 0b265a9f62db554fa9aba6dd19e1bd5704bc7d8a'


class PinTests(unittest.TestCase):
    def body(self):
        return (ROOT/'scripts/rehearsal_prep.sh').read_text().split('[[ ${REHEARSAL:-0} == 1 ]]',1)[0]

    def test_pins_match_the_recorded_gpu_baseline(self):
        gpu=json.loads((ROOT/'results/droplet_logs/session2_attempt3/bootstrap_versions.json').read_text())
        self.assertEqual(gpu['docker'],'Docker version 29.8.2, build 7fc2dff')
        self.assertEqual(gpu['buildx'],BUILDX)
        self.assertIn(ENGINE_APT,self.body());self.assertIn(BUILDX_APT,self.body());self.assertIn(BUILDX,self.body())

    def test_installs_only_exact_apt_versions_and_holds_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bin=root/'bin';bin.mkdir();calls=root/'calls'
            for name in ('apt-get','apt-mark','systemctl'):
                p=bin/name;p.write_text('#!/bin/sh\necho "'+name+' $*" >> "$CALLS"\n');p.chmod(0o755)
            result=subprocess.run(['bash','-eu'],input=self.body()+'\ninstall_versions\n',env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],CALLS=str(calls)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            text=calls.read_text()
            for p,v in [('docker-ce',ENGINE_APT),('docker-ce-cli',ENGINE_APT),('docker-buildx-plugin',BUILDX_APT)]:self.assertIn(p+'='+v,text)
            self.assertIn('--allow-downgrades',text);self.assertIn('--no-remove',text)
            self.assertIn('apt-mark hold docker-ce docker-ce-cli docker-buildx-plugin',text)
            self.assertTrue(text.rstrip().endswith('systemctl restart docker'))

    def test_repository_setup_creates_signed_source_or_reuses_existing_without_conflict(self):
        for existing in (False,True):
            with self.subTest(existing=existing),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);apt=root/'etc/apt';sources=apt/'sources.list.d';sources.mkdir(parents=True);bin=root/'bin';bin.mkdir();calls=root/'calls'
                if existing:
                    (sources/'docker.sources').write_text('URIs: https://download.docker.com/linux/ubuntu\nSigned-By: /existing/docker.asc\n')
                curl=bin/'curl';curl.write_text('#!/bin/sh\necho curl >> "$CALLS"\nwhile [ "$1" != -o ]; do shift; done\nprintf "fixture-key" > "$2"\n');curl.chmod(0o755)
                body=self.body().replace('/etc/apt',str(apt))
                result=subprocess.run(['bash','-eu'],input=body+'\nconfigure_repository\n',env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],CALLS=str(calls)),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                if existing:
                    self.assertFalse(calls.exists());self.assertFalse((sources/'rocm006-rehearsal-docker.sources').exists())
                    self.assertIn('Reusing configured Docker apt repository',result.stdout)
                else:
                    source=(sources/'rocm006-rehearsal-docker.sources').read_text()
                    self.assertIn('Signed-By: '+str(apt)+'/keyrings/rocm006-rehearsal-docker.asc',source)
                    self.assertIn('Suites: noble',source)
                    self.assertEqual(calls.read_text(),'curl\n')

    def test_strict_versions_fail_and_always_save_a_verification_record(self):
        base=dict(Client=dict(Version='29.8.2',GitCommit='7fc2dff',Os='linux',Arch='amd64'),Server=dict(Version='29.8.2',Os='linux',Arch='amd64'))
        cases=[('good',{}),('client',dict(client='29.9.1')),('daemon',dict(server='29.9.1')),('build',dict(commit='wrong')),('plugin',dict(buildx='github.com/docker/buildx v0.38.0 wrong')),('package',dict(package='0.38.0-wrong')),('platform',dict(arch='arm64'))]
        for name,changes in cases:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);bin=root/'bin';bin.mkdir();docker=bin/'docker'
                actual=json.loads(json.dumps(base));actual['Client']['Version']=changes.get('client','29.8.2');actual['Client']['GitCommit']=changes.get('commit','7fc2dff');actual['Server']['Version']=changes.get('server','29.8.2');actual['Server']['Arch']=changes.get('arch','amd64')
                docker.write_text('#!/bin/sh\nif [ "$1" = version ]; then echo "$DOCKER_JSON"; else echo "$BUILDX_VERSION_OUTPUT"; fi\n');docker.chmod(0o755)
                pkg=bin/'dpkg-query';pkg.write_text('#!/bin/sh\ncase "$3" in docker-buildx-plugin) echo "$PKG_BUILDX";; *) echo "'+ENGINE_APT+'";; esac\n');pkg.chmod(0o755)
                ident=bin/'id';ident.write_text('#!/bin/sh\nexit 1\n');ident.chmod(0o755)
                body=self.body().replace('/usr/bin/docker',str(docker)).replace('/usr/local/bin/docker',str(docker))
                env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],DOCKER_JSON=json.dumps(actual),BUILDX_VERSION_OUTPUT=changes.get('buildx',BUILDX),PKG_BUILDX=changes.get('package',BUILDX_APT))
                result=subprocess.run(['bash','-eu'],input=body+'\nverify_versions '+str(root)+'\n',env=env,capture_output=True,text=True)
                record=json.loads((root/'results/rehearsal/logs/rehearsal_prep_versions.json').read_text())
                self.assertEqual(result.returncode==0,name=='good',result.stderr)
                self.assertEqual(record['verified'],name=='good')
                self.assertEqual(record['fs_read_grant'],str(root)+'/results/rehearsal/atlas/data')
                if name!='good':self.assertTrue(record['provenance_errors'])


class EnvironmentTests(unittest.TestCase):
    def test_launcher_grants_only_bake_in_the_rehearsal_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();atlas=root/'atlas';atlas.mkdir();other=root/'other';other.mkdir();argsfile=root/'args'
            backend=root/'real-docker';backend.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\n');backend.chmod(0o755)
            launcher=root/'docker';launcher.write_text((ROOT/'scripts/rehearsal_docker.sh').read_text().replace('@REHEARSAL_STUDY_ROOT@',str(root)).replace('/usr/bin/docker',str(backend)))
            for mode,cwd,args,grant in [('1',atlas,['buildx','bake','-f','bake.json','strtok3','--load'],True),('0',atlas,['buildx','bake','strtok3'],False),('1',other,['buildx','bake','strtok3'],False),('1',atlas,['buildx','version'],False),('1',atlas,['version'],False)]:
                result=subprocess.run(['bash',str(launcher),*args],cwd=cwd,env=dict(os.environ,REHEARSAL=mode,ARGS_FILE=str(argsfile)),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                actual=argsfile.read_text().splitlines()
                expected=args[:2]+['--allow=fs.read='+str(root)+'/results/rehearsal/atlas/data']+args[2:] if grant else args
                self.assertEqual(actual,expected)
                self.assertFalse(any('fs.write=' in a or 'fs.read=*' in a for a in actual))

    def test_prep_and_driver_dry_runs_never_dispatch_and_prep_is_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'unexpected'
            for name in ('ssh','scp','apt-get','apt-mark','docker','systemctl'):
                p=root/name;p.write_text('#!/bin/sh\ntouch "$MARKER"\nexit 88\n');p.chmod(0o755)
            env=dict(os.environ,REHEARSAL='1',ATLAS_SSH_TARGET='root@cpu.example',ATLAS_REMOTE_ROOT='<HOME>/reh001-rehearsal',PATH=str(root)+':'+os.environ['PATH'],MARKER=str(marker))
            result=subprocess.run(['python3',str(ROOT/'scripts/rehearse_006.py'),'--dry-run'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertLess(result.stdout.index('rehearsal_prep.sh'),result.stdout.index('atlas_remote.sh'))
            self.assertIn(ENGINE_APT,result.stdout);self.assertIn('--allow=fs.read=',result.stdout)
            self.assertFalse(marker.exists())
            result=subprocess.run(['bash',str(ROOT/'scripts/rehearsal_prep.sh'),'--dry-run'],env=dict(env,REHEARSAL='0'),capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(marker.exists())

    def test_prep_failure_stops_driver_before_any_native_setup(self):
        calls=[]
        def command(args,**kwargs):
            calls.append(args)
            raise subprocess.CalledProcessError(1,args)
        with patch.dict(os.environ,REHEARSAL='1',ATLAS_SSH_TARGET='root@cpu.example',ATLAS_REMOTE_ROOT='<HOME>/reh001-rehearsal'),patch.object(driver.subprocess,'run',command):
            with self.assertRaises(subprocess.CalledProcessError):driver.run()
        self.assertEqual(len(calls),1);self.assertTrue(calls[0][1].endswith('/rehearsal_prep.sh'))

    def test_atlas_version_mismatch_after_setup_stops_before_probe(self):
        calls=[]
        def command(args,**kwargs):
            calls.append(args)
            output=''
            if args[0]=='ssh':
                if 'bootstrap_versions.json' in args[-1]:
                    output=json.dumps(dict(docker='Docker version 29.9.1, build wrong',buildx=BUILDX))
                else:
                    output=json.dumps(dict(job=dict(status='DONE',exit_code=0),busy=False))
            return subprocess.CompletedProcess(args,0,output,'')
        with patch.dict(os.environ,REHEARSAL='1',ATLAS_SSH_TARGET='root@cpu.example',ATLAS_REMOTE_ROOT='<HOME>/reh001-rehearsal'),patch.object(driver.subprocess,'run',command):
            with self.assertRaisesRegex(ValueError,'stop before probe'):driver.run()
        self.assertTrue(calls[0][1].endswith('/rehearsal_prep.sh'))
        self.assertTrue(any(a[-1]=='setup' for a in calls));self.assertFalse(any(a[-1]=='probe' for a in calls))


if __name__=='__main__':unittest.main()
