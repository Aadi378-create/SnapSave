"""Create and verify a consistent SQLite snapshot, including committed WAL data.

Backups contain private customer data. Keep them out of Git/static hosting and
copy verified snapshots to encrypted offline/versioned storage for ransomware recovery.
"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def backup_database(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():raise ValueError('Source database does not exist')
    destination.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=destination/f'snapsave-{stamp}-{uuid.uuid4().hex[:10]}.sqlite3'
    with target.open('xb'):pass
    deadline=time.monotonic()+120
    def progress(*_):
        if time.monotonic()>deadline:raise TimeoutError('Database backup exceeded two minutes')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)) as original:
            with closing(sqlite3.connect(target)) as snapshot:
                original.backup(snapshot,pages=256,progress=progress,sleep=0.05)
                integrity=[r[0] for r in snapshot.execute('PRAGMA integrity_check')]
                if integrity!=['ok']:raise ValueError('Snapshot integrity check failed')
        with target.open('rb') as contents:digest=hashlib.file_digest(contents,'sha256').hexdigest()
        manifest={'file':target.name,'created_at':datetime.now(timezone.utc).isoformat(),
                  'bytes':target.stat().st_size,'sha256':digest,'integrity_check':'ok'}
        with target.with_suffix('.manifest.json').open('x',encoding='utf-8') as output:
            json.dump(manifest,output,indent=2)
        return target,manifest
    except Exception:
        target.unlink(missing_ok=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    from database import DATABASE_URL
    from settings import BASE_DIR
    if DATABASE_URL.get_backend_name()!='sqlite' or not DATABASE_URL.database or DATABASE_URL.database==':memory:':
        parser.error('Use your database vendor backup tooling for non-file SQLite databases')
    target,manifest=backup_database(DATABASE_URL.database,args.output_dir or BASE_DIR.parent/'.private-backups')
    print(json.dumps({'backup_file':str(target),**manifest},indent=2))


if __name__=='__main__':main()
