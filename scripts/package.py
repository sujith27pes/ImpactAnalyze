"""Package source only. Never include keys, venvs, repository builds or runtime databases."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
destination=root.parent/'impact-studio.zip'
excluded={'.git','.venv','target','data','__pycache__','.pytest_cache'}
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(root.rglob('*')):
        relative=file.relative_to(root)
        if not file.is_file() or file.is_symlink() or any(p in excluded for p in relative.parts): continue
        if file.name=='.env' or file.suffix in {'.log','.pyc','.db'}: continue
        archive.write(file,'impact-studio/'+relative.as_posix())
print(destination)
