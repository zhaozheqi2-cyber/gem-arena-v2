"""Replay every logged transition and check the tournament accounting."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from .game import Game,VERSION

def verify(folder):
    folder=Path(folder)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['rules']==VERSION, 'Use the verifier for this rules version'
    assert manifest['data_sha256']==hashlib.sha256((Path(__file__).resolve().parents[1]/'data/base.json').read_bytes()).hexdigest()
    assert len(summary['results'])==summary['games']==manifest['games']
    wins=[0,0];draws=0;faults=[0,0];illegal=[0,0];scores=[0,0];times=[0.0,0.0];caps=0
    for i in range(summary['games']):
        r=json.loads((folder/f'game_{i+1:02}.json').read_text(encoding='utf-8'))
        assert r['game']==i+1 and r['rules']==VERSION and r['names']==manifest['names']==summary['names']
        assert r['seed']==manifest['base_seed']+i//2
        assert r['order']==([0,1] if i%2==0 else [1,0])
        g=Game(r['seed'],max_turns=manifest['max_turns']);assert g.snapshot()==r['frames'][0]['state']
        failed=None
        local_faults=[0,0];local_illegal=[0,0];local_times=[0.0,0.0]
        for frame in r['frames'][1:]:
            assert not g.done,'extra action after end'
            event=frame['event'];seat=g.turn%2;who=r['order'][seat]
            assert event['seat']==seat and event['agent']==who
            assert event['decision']==g.decisions+1 and event['phase']==g.phase
            assert event['ply']==g.turn+1 and math.isfinite(event['elapsed_ms']) and event['elapsed_ms']>=0
            if event['status']=='ok':
                assert type(event['action_index']) is int and 0<=event['action_index']<len(g.legal_actions())
                assert g.legal_actions()[event['action_index']]==event['action']
                g.step(event['action'])
            else:
                failed=who
                assert event['action'] is None
                faults[who]+=1;illegal[who]+=int(event['status']=='illegal_action')
                local_faults[who]+=1;local_illegal[who]+=int(event['status']=='illegal_action')
                g.done=True;g.reason='forfeit:'+event['status']
            times[who]+=event['elapsed_ms']
            local_times[who]+=event['elapsed_ms']
            assert g.snapshot()==frame['state']
        assert g.done
        w=g.winner() if failed is None else None
        expected=1-failed if failed is not None else (None if w is None else r['order'][w])
        assert expected==r['winner'] and r['reason']==g.reason
        assert r['turns']==g.turn
        assert r['decisions']==g.decisions and r['max_turns']==g.max_turns
        assert r['faults']==local_faults and r['illegal_actions']==local_illegal
        assert all(abs(a-b)<0.2 for a,b in zip(r['elapsed_ms'],local_times))
        if expected is None:draws+=1
        else:wins[expected]+=1
        for seat,who in enumerate(r['order']):
            assert r['scores'][who]==g.players[seat]['score']
            assert r['cards'][who]==len(g.players[seat]['cards'])
            scores[who]+=r['scores'][who]
        caps+=int(r['reason']=='turn_limit')
        assert {k:v for k,v in r.items() if k!='frames'}==summary['results'][i]
    assert wins==summary['wins'] and draws==summary['draws']
    assert faults==summary['faults'] and illegal==summary['illegal_actions']
    assert [round(s/summary['games'],2) for s in scores]==summary['mean_scores']
    assert caps==summary['turn_limit_games']
    assert all(abs(t-summary['elapsed_ms'][i])<1 for i,t in enumerate(times))
    print(f"Verified {summary['games']} games: all transitions, paired seats, winners and totals.")

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');verify(p.parse_args().folder)
