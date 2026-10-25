"""Package the existing, tested capture script for an explicit Edge toolbar click."""
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED


def build(destination=None):
    root=Path(__file__).resolve().parent
    target=Path(destination) if destination else root/'dist'
    target.mkdir(parents=True,exist_ok=True)
    allowed={'manifest.json','background.js','capture.js','snapsave-retailer-capture.zip'}
    if any(p.is_symlink() or p.is_dir() or p.name not in allowed for p in target.iterdir()):
        raise ValueError('Use a fresh extension output directory')
    script=(root.parent/'export_catalogue_capture.js').read_text(encoding='utf-8').rstrip()
    if not script.endswith('})();'):
        raise ValueError('Unexpected exporter format; review the extension wrapper before packaging')
    # Keep one capture implementation; expose its result to the toolbar worker.
    wrapped=script[:-len('})();')]+'''})().then(()=>({ok:true}),error=>{
        alert('SnapSave capture stopped: '+error.message);
        return {ok:false,error:String(error.message)};
    });\n'''
    for name in ('manifest.json','background.js'):
        shutil.copy2(root/name,target/name)
    (target/'capture.js').write_text(wrapped,encoding='utf-8')
    archive=target/'snapsave-retailer-capture.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as output:
        for name in ('manifest.json','background.js','capture.js'):
            output.write(target/name,name)
    return target


if __name__=='__main__':print(build())
