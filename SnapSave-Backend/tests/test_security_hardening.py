import asyncio
from functools import partial
import hashlib
import http.server
import importlib.util
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest
import requests


def test_host_validation_blocks_rebinding_but_ignores_forwarded_host(client):
    assert client.get('/',headers={'Host':'attacker.example'}).status_code==400
    assert client.get('/',headers={'X-Forwarded-Host':'attacker.example'}).status_code==200


def test_api_responses_are_not_cacheable_or_frameable(client):
    response=client.get('/api/auth/me')
    assert response.status_code==401
    assert response.headers['Cache-Control']=='no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert response.headers['X-Frame-Options']=='DENY'


def test_read_limit_cannot_be_evaded_with_forwarded_ips(client):
    for i in range(300):assert client.get('/',headers={'X-Forwarded-For':f'192.0.2.{i%255}'}).status_code==200
    response=client.get('/')
    assert response.status_code==429 and response.headers['Retry-After']=='60'


def test_development_auth_has_a_separate_strict_limit(client):
    for _ in range(10):assert client.get('/api/auth/test-token',params={'phone':'+919999999999'}).status_code==200
    assert client.get('/api/auth/test-token',params={'phone':'+919999999999'}).status_code==429
    assert client.get('/').status_code==200


def test_oversized_headers_and_declared_bodies_stop_before_auth(client):
    assert client.get('/api/auth/me',headers={'Authorization':'Bearer '+'x'*8193}).status_code==431
    response=client.post('/api/help',content='{}',headers={'Content-Length':'70000'})
    assert response.status_code==413


def test_slow_stream_is_bounded(monkeypatch):
    import api.guardrails as guardrails
    original_timeout=asyncio.timeout
    monkeypatch.setattr(guardrails.asyncio,'timeout',lambda _:original_timeout(.01))
    class SlowRequest:
        method='POST';url=SimpleNamespace(path='/api/help');client=SimpleNamespace(host='127.0.0.1');headers={}
        async def stream(self):
            yield b'{' 
            await asyncio.sleep(.1)
    async def never_called(*_):raise AssertionError('Slow body reached application')
    response=asyncio.run(guardrails.RequestLimits(None).dispatch(SlowRequest(),never_called))
    assert response.status_code==408


def test_frontend_server_denies_source_logs_dotfiles_and_directory_listing(tmp_path):
    source=Path(__file__).resolve().parents[2]/'SnapSave-FRONTEND/serve.py'
    spec=importlib.util.spec_from_file_location('secure_frontend',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('index.html','admin.html','.env','serve.py','private.log'):(tmp_path/name).write_text('fixture')
    (tmp_path/'assets').mkdir();(tmp_path/'assets/image.png').write_bytes(b'fixture');(tmp_path/'assets/secret.json').write_text('private')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(module.NoCacheHandler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    session=requests.Session();session.trust_env=False
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        assert session.get(base+'/').status_code==200
        response=session.get(base+'/admin.html');assert response.status_code==200
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        assert session.get(base+'/assets/image.png').status_code==200
        for path in ('.env','%2eenv','serve.py','private.log','assets/','assets/secret.json'):
            assert session.get(base+'/'+path).status_code==404
        assert session.get(base+'/',headers={'Host':'attacker.example'}).status_code==400
    finally:
        session.close();server.shutdown();server.server_close();thread.join(timeout=3)


def test_online_backup_contains_wal_data_and_can_be_restored(tmp_path):
    from backup_database import backup_database
    source=tmp_path/'source.sqlite3'
    original=sqlite3.connect(source)
    try:
        original.execute('PRAGMA journal_mode=WAL')
        original.execute('CREATE TABLE records (id INTEGER PRIMARY KEY,value TEXT)')
        original.execute("INSERT INTO records(value) VALUES ('saved customer record')");original.commit()
        target,manifest=backup_database(source,tmp_path/'backups')
        assert manifest['integrity_check']=='ok'
        assert hashlib.sha256(target.read_bytes()).hexdigest()==manifest['sha256']
        assert json.loads(target.with_suffix('.manifest.json').read_text())==manifest
        with sqlite3.connect(target) as snapshot:
            assert snapshot.execute('SELECT value FROM records').fetchone()[0]=='saved customer record'
            with sqlite3.connect(tmp_path/'restored.sqlite3') as restored:
                snapshot.backup(restored)
                assert restored.execute('SELECT count(*) FROM records').fetchone()[0]==1
        original.execute("INSERT INTO records(value) VALUES ('still writable')");original.commit()
    finally:original.close()


def test_hosting_builder_rejects_stale_private_files(tmp_path):
    source=Path(__file__).resolve().parents[2]/'SnapSave-FRONTEND/prepare_hosting.py'
    spec=importlib.util.spec_from_file_location('safe_hosting',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=tmp_path/'dist';target.mkdir();(target/'customer-data.sqlite3').write_text('private fixture')
    with pytest.raises(ValueError,match='unexpected files'):module.prepare('https://api.example.com',target)
    assert (target/'customer-data.sqlite3').read_text()=='private fixture'
    for value in ('assets/.env','assets/service-account.json','secret.log'):
        assert not module.public_output(Path(value))
