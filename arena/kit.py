"""One identical development packet, excluding private submissions and runs."""
import argparse
import hashlib
from pathlib import Path
import zipfile

def build(destination):
    root=Path(__file__).resolve().parents[1]
    files=[root/n for n in ('README.md','RULES.md','AGENT_API.md','PARTICIPANT_PROMPT.md',
        'ENGINE_REVIEW.md','LICENSE','Dockerfile','run-demo.cmd')]
    for folder in ('arena','agents','tests','data','third_party'):
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files): z.write(p,p.relative_to(root))
    with zipfile.ZipFile(destination) as z: assert z.testzip() is None
    print(f'Identical v2 packet: {destination}\nSHA256 {hashlib.sha256(Path(destination).read_bytes()).hexdigest()}')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination',nargs='?',default='participant-kit-v2.zip')
    build(p.parse_args().destination)
