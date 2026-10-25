"""Build an allowlisted hosting directory with an explicit HTTPS API origin."""
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlparse

PUBLIC_FILES={"index.html","admin.html","common.js","phone-login.js","phone-login.css","conversation.js","conversation.css","404.html","config.js"}
PUBLIC_LICENSES={'assets/vendor/fontawesome/LICENSE.txt','assets/vendor/fonts/outfit-OFL.txt','assets/vendor/fonts/plusjakartasans-OFL.txt','assets/vendor/fonts/jetbrainsmono-OFL.txt'}
ASSET_TYPES={'.png','.jpg','.jpeg','.webp','.gif','.svg','.ico','.css','.js','.woff','.woff2','.ttf'}

def public_output(path):
    return path.as_posix() in PUBLIC_FILES or path.as_posix() in PUBLIC_LICENSES or (len(path.parts)>1 and path.parts[0]=='assets' and path.suffix.lower() in ASSET_TYPES and not any(part.startswith('.') for part in path.parts))

def prepare(origin, destination=None):
    parsed=urlparse(origin)
    if parsed.scheme!="https" or not parsed.netloc or parsed.path not in {"","/"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API_ORIGIN must be an HTTPS origin, such as https://api.example.com")
    root=Path(__file__).resolve().parent
    target=Path(destination) if destination else root/"dist"
    target.mkdir(parents=True,exist_ok=True)
    # Fail rather than leave an old secret/database/log in a reused build.
    if any(path.is_symlink() or (path.is_file() and not public_output(path.relative_to(target))) for path in target.rglob('*')):
        raise ValueError('Hosting output contains unexpected files; use a fresh empty destination')
    for name in ("index.html","admin.html","common.js","phone-login.js","phone-login.css","conversation.js","conversation.css","404.html"):
        shutil.copy2(root/name,target/name)
    (target/"config.js").write_text("window.SNAPSAVE_API_BASE="+json.dumps(origin.rstrip("/"))+";\n",encoding="utf-8")
    assets=(root/'assets').resolve()
    for source in assets.rglob('*'):
        if source.is_file() and public_output(Path('assets')/source.relative_to(assets)) and source.resolve().is_relative_to(assets) and not any(part.startswith('.') for part in source.relative_to(assets).parts):
            output=target/'assets'/source.relative_to(assets);output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,output)
    return target

if __name__=="__main__":
    print(prepare(os.environ["API_ORIGIN"]))
