import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from arena.game import VERSION
from arena.tournament import play
from arena.verify import verify


class VerifyTests(unittest.TestCase):
    def fixture(self,folder):
        class Inline:
            def call(self,o,m):
                buys=[i for i,a in enumerate(o['legal_actions']) if a['type']=='buy']
                return (buys[0] if buys else 0),None,'ok',0.1
        rows=[]
        for i in range(2):
            r=play(19,[0,1] if i==0 else [1,0],[Inline(),Inline()],max_turns=80)
            r.update(game=i+1,names=['A','B'],rules=VERSION)
            (folder/f'game_{i+1:02}.json').write_text(json.dumps(r),encoding='utf-8')
            rows.append({k:v for k,v in r.items() if k!='frames'})
        summary=dict(games=2,names=['A','B'],wins=[sum(r['winner']==i for r in rows) for i in (0,1)],
            draws=sum(r['winner'] is None for r in rows),
            faults=[sum(r['faults'][i] for r in rows) for i in (0,1)],
            illegal_actions=[sum(r['illegal_actions'][i] for r in rows) for i in (0,1)],
            mean_scores=[round(sum(r['scores'][i] for r in rows)/2,2) for i in (0,1)],
            elapsed_ms=[sum(r['elapsed_ms'][i] for r in rows) for i in (0,1)],
            turn_limit_games=sum(r['reason']=='turn_limit' for r in rows),results=rows)
        (folder/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
        data=Path(__file__).resolve().parents[1]/'data/base.json'
        manifest=dict(games=2,names=['A','B'],base_seed=19,max_turns=80,rules=VERSION,
                      data_sha256=hashlib.sha256(data.read_bytes()).hexdigest())
        (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')

    def test_verify_and_reject_modified_transition(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            folder=Path(d);self.fixture(folder)
            with contextlib.redirect_stdout(io.StringIO()):verify(folder)
            path=folder/'game_01.json';r=json.loads(path.read_text(encoding='utf-8'))
            r['frames'][1]['state']['bank'][0]+=1
            path.write_text(json.dumps(r),encoding='utf-8')
            with self.assertRaises(AssertionError):verify(folder)

    def test_verify_rejects_false_accounting(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            folder=Path(d);self.fixture(folder)
            path=folder/'game_01.json';r=json.loads(path.read_text(encoding='utf-8'))
            r['cards'][0]+=1;path.write_text(json.dumps(r),encoding='utf-8')
            with self.assertRaises(AssertionError):verify(folder)

if __name__=='__main__':unittest.main()
