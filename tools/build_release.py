"""Build an allowlisted, credential-free student checkout and ZIP."""
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def build(root=ROOT):
    root=Path(root);destination=root/'release'/'github';destination.mkdir(parents=True,exist_ok=True)
    paths=[root/name for name in ['reel.py','AGENTS.md','README.md','ONBOARDING.md','.gitignore','.env.example','requirements.txt','requirements-local.txt']]
    for folder,pattern in [('reel_engine','*.py'),('tests','test_*.py'),('templates','*.json'),('assets','*-OFL.txt'),('assets','*.ttf'),('tools','build_release.py')]:paths+=list((root/folder).glob(pattern))
    paths.append(root/'assets'/'cta'/'watch-full-video.mp4')
    allowed={str(path.relative_to(root)).replace('\\','/') for path in paths}
    # Refuse to reuse a polluted export; never delete an unknown local tree.
    generated={'.git','__pycache__','.pytest_cache'}
    existing={str(path.relative_to(destination)).replace('\\','/') for path in destination.rglob('*') if path.is_file() and not any(part in generated for part in path.relative_to(destination).parts)}
    if existing-allowed:raise ValueError('Release folder contains unexpected files. Inspect it before rebuilding.')
    secret=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})')
    for path in paths:
        if not path.is_file():raise ValueError('Missing release file: '+str(path.relative_to(root)))
        data=path.read_bytes()
        if path.suffix in ('.py','.md','.json','.txt') or path.name.startswith('.env'):
            if secret.search(data):raise ValueError('Potential credential in release file: '+str(path.relative_to(root)))
        if path.name=='AGENTS.md':
            data=data.replace(b'C:/Users/sharm/Downloads/web-3-reel-locked-captions.mp4',b'optional local approved reference (not distributed)')
        target=destination/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    archive=root/'release'/'codex-reel-student-workflow.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as zipped:
        for relative in sorted(allowed):zipped.write(destination/relative,arcname='codex-reel-workflow/'+relative)
    return {'repository_folder':str(destination.resolve()),'zip':str(archive.resolve()),'files':len(allowed),'private_state_included':False}


if __name__=='__main__':print(json.dumps(build(),indent=2))
