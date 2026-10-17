"""Build an allowlisted hosting directory with an explicit HTTPS API origin."""
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlparse

def prepare(origin, destination=None):
    parsed=urlparse(origin)
    if parsed.scheme!="https" or not parsed.netloc or parsed.path not in {"","/"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API_ORIGIN must be an HTTPS origin, such as https://api.example.com")
    root=Path(__file__).resolve().parent
    target=Path(destination) if destination else root/"dist"
    target.mkdir(parents=True,exist_ok=True)
    for name in ("index.html","admin.html","common.js","phone-login.js","phone-login.css","404.html"):
        shutil.copy2(root/name,target/name)
    (target/"config.js").write_text("window.SNAPSAVE_API_BASE="+json.dumps(origin.rstrip("/"))+";\n",encoding="utf-8")
    shutil.copytree(root/"assets",target/"assets",dirs_exist_ok=True)
    return target

if __name__=="__main__":
    print(prepare(os.environ["API_ORIGIN"]))
