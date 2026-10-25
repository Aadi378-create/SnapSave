"""Restore a backup into a disposable database and verify it without replacing app data."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

def verify_backup(source,expected_sha256=None):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('Backup does not exist')
    with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if expected_sha256 is not None and digest!=expected_sha256:raise ValueError('Backup checksum mismatch')
    deadline=time.monotonic()+120
    def progress(*_):
        if time.monotonic()>deadline:raise TimeoutError('Backup restore check exceeded two minutes')
    with tempfile.TemporaryDirectory(prefix='snapsave-restore-check-') as folder:
        restored=Path(folder)/'restored.sqlite3'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)) as original:
            original.execute('PRAGMA trusted_schema=OFF')
            with closing(sqlite3.connect(restored)) as target:
                original.backup(target,pages=256,progress=progress,sleep=.05)
                target.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
                if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Restored database integrity check failed')
                if target.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Restored database foreign-key check failed')
                target.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
    return {'restored':True,'integrity_check':'ok','foreign_key_check':'ok','sha256':digest}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('backup',type=Path);parser.add_argument('--manifest',type=Path);args=parser.parse_args()
    digest=json.loads(args.manifest.read_text(encoding='utf-8'))['sha256'] if args.manifest else None
    print(json.dumps(verify_backup(args.backup,digest),indent=2))

if __name__=='__main__':main()
