"""Extract both official archives into one empty directory for offline replay."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='runs/official');args=parser.parse_args()
    dest=(ROOT/args.out).resolve()
    if dest.exists() and any(dest.iterdir()):raise SystemExit('Output is not empty; select another --out directory.')
    config=json.loads((ROOT/'competition.json').read_text(encoding='utf-8'))
    for item in config['archives']:
        archive=ROOT/item['file']
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==item['sha256']
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                assert (dest/info.filename).resolve().is_relative_to(dest),'Archive path outside output'
            z.extractall(dest)
    print('Latest report:',dest/'v2-six-way-750-overtime/index.html')
    print('Original replays:',dest/'v2-six-way-750/index.html')

if __name__=='__main__':main()
