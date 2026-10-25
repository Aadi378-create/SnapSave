"""Explicit local maintenance tool. Stop API writers before resetting development orders."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from backup_database import backup_database


def reset_order_data(source,backup_dir):
    source=Path(source).resolve()
    snapshot,manifest=backup_database(source,backup_dir)
    with closing(sqlite3.connect(source.as_uri()+'?mode=rw',uri=True,timeout=10)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            before={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                    for table in ('users','addresses','orders','order_items','messages','feedbacks','incidents')}
            db.execute('DELETE FROM incidents WHERE order_id IS NOT NULL')
            db.execute('DELETE FROM messages WHERE order_id IS NOT NULL')
            db.execute('DELETE FROM feedbacks')
            db.execute('DELETE FROM order_items')
            db.execute('DELETE FROM orders')
            db.execute('UPDATE users SET completed_orders_count=0')
            if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foreign key check failed')
            if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('Integrity check failed')
            after={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in before}
            db.commit()
        except Exception:
            db.rollback();raise
    return {'backup_file':str(snapshot),'backup_sha256':manifest['sha256'],'integrity_check':'ok','before':before,'after':after}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-development-orders-reset',action='store_true',required=True)
    parser.parse_args()
    from database import DATABASE_URL
    from settings import BASE_DIR
    if DATABASE_URL.get_backend_name()!='sqlite':parser.error('Only a local SQLite development database is supported')
    source=Path(DATABASE_URL.database).resolve()
    if not source.is_relative_to(BASE_DIR):parser.error('Database must be inside this backend directory')
    import json
    print(json.dumps(reset_order_data(source,BASE_DIR.parent/'.private-backups'),indent=2))

if __name__=='__main__':main()
