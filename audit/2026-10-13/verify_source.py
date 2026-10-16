"""Syntax-only verification; never imports the API or opens its database."""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def verify():
    files=list((ROOT/"SnapSave-Backend").rglob("*.py"))+list((ROOT/"SnapSave-FRONTEND").glob("*.py"))
    files=[p for p in files if "__pycache__" not in p.parts and ".venv" not in p.parts]
    for path in files:
        ast.parse(path.read_text(encoding="utf-8-sig"),filename=str(path))
    node=shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for JavaScript syntax checks")
    scripts=0
    for path in (ROOT/"SnapSave-FRONTEND").glob("*.js"):
        subprocess.run([node,"--check",str(path)],check=True,capture_output=True,text=True,encoding="utf-8")
        scripts+=1
    for path in (ROOT/"SnapSave-FRONTEND").glob("*.html"):
        for attributes,source in re.findall(r"<script\b([^>]*)>(.*?)</script>",path.read_text(encoding="utf-8"),re.S):
            if "src=" in attributes or not source.strip():
                continue
            subprocess.run([node,"--input-type=module","--check"],input=source,check=True,capture_output=True,text=True,encoding="utf-8")
            scripts+=1
    json.loads((ROOT/"SnapSave-FRONTEND/firebase.json").read_text(encoding="utf-8"))
    result={"python_files_parsed":len(files),"javascript_scripts_parsed":scripts,"hosting_json_valid":True,"python":sys.version.split()[0],"node":subprocess.check_output([node,"--version"],text=True).strip()}
    (Path(__file__).with_name("source-verification.json")).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    verify()
