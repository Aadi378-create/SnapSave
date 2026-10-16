"""Atomic local-file replacement. Callers serialize read/modify/write with a lock."""
import json
import os
from pathlib import Path
import tempfile

def read_json(path, default=None):
    source=Path(path)
    if not source.exists():
        return {} if default is None else default
    with source.open(encoding="utf-8") as file:
        return json.load(file)

def write_json(path, value):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=target.parent,suffix=".tmp",delete=False) as file:
            temporary=Path(file.name)
            json.dump(value,file,indent=2,allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary,target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
