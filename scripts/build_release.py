"""Package source only; exclude local secrets, environments, logs and data backups."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
output=ROOT.parent/'海运订舱系统_程序源码.zip'
directories=('app','sql','scripts','docs','tests')
files=[ROOT/name for name in ('README.md','requirements.txt','requirements-dev.txt','requirements-lock.txt','.env.example','run.py','setup.ps1','start.cmd','stop.cmd')]
for directory in directories:
    files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and not any(part in ('__pycache__','.pytest_cache','node_modules') for part in p.parts) and p.suffix not in ('.pyc','.bak'))
manifest=[]
with ZipFile(output,'w',ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(set(files)):
        relative=path.relative_to(ROOT).as_posix()
        payload=path.read_bytes()
        archive.writestr('shipping_booking/'+relative,payload)
        manifest.append(hashlib.sha256(payload).hexdigest()+'  '+relative)
    archive.writestr('shipping_booking/SHA256SUMS.txt','\n'.join(manifest)+'\n')
print(f'{output}\n{len(manifest)} source files; {output.stat().st_size:,} bytes. No .env or virtual environments included.')
