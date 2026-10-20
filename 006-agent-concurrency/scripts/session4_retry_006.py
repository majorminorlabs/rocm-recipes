#!/usr/bin/env python3
"""Explicit new infra attempts, retaining every original DB row; maximum two retries."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
from session4_006 import save


def retry(campaign, dbpath, level, number):
    base=json.loads((campaign/(level+'.json')).read_text())
    previous=campaign/(f'{level}-retry{number-1}.json') if number>1 else campaign/(level+'.json')
    if not previous.exists():
        return None
    manifest=json.loads(previous.read_text())
    db=sqlite3.connect(dbpath);db.row_factory=sqlite3.Row
    selected=[]
    live=dbpath.parent/'live'/level/'runs.json'
    exported={r['run_id']:r for r in json.loads(live.read_text())['rows']} if live.exists() else {}
    try:
        for spec in manifest['runs']:
            run=f"{spec['task']}__{spec['config']}__a{spec['attempt']}"
            row=db.execute('SELECT * FROM runs WHERE run_id=?',(run,)).fetchone()
            if not row or row['state']!='finished':
                raise ValueError('Retry check requires completed execution/export')
            if row['end_reason']!='infra' and row['category']!='infra_error' and exported.get(run,{}).get('category')!='infra_error':
                continue
            ancestor=row;depth=0
            while ancestor['retry_of']:
                depth+=1
                ancestor=db.execute('SELECT * FROM runs WHERE run_id=?',(ancestor['retry_of'],)).fetchone()
                if ancestor is None:
                    raise ValueError('Broken infra retry chain')
            if depth>=2:
                continue
            selected.append(dict(task=spec['task'],config=spec['config'],attempt=1000+int(level[1:])*10+number,retryOf=run))
    finally:
        db.close()
    if not selected:
        return None
    m=copy.deepcopy(base);m.update(id=base['id']+f'-retry{number}',runs=selected)
    path=campaign/f'{level}-retry{number}.json';save(path,m)
    return path


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaign',type=Path);p.add_argument('db',type=Path);p.add_argument('level');p.add_argument('number',type=int)
    a=p.parse_args();path=retry(a.campaign,a.db,a.level,a.number)
    if path:print(path)
