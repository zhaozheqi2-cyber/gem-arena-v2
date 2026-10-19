"""Verify published official records without rerunning any submitted agent."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena.game import Game

def replay(g,record):
    assert g.snapshot()==record['frames'][0]['state']
    for frame in record['frames'][1:]:
        event=frame['event'];seat=g.turn%2;who=record['order'][seat]
        assert not g.done
        assert (event['seat'],event['agent'],event['phase'],event['ply'],event['decision'])==(seat,who,g.phase,g.turn+1,g.decisions+1)
        if event['status']=='ok':
            assert type(event['action_index']) is int
            assert g.legal_actions()[event['action_index']]==event['action']
            g.step(event['action'])
        else:
            assert event['action'] is None
            g.done=True;g.reason='forfeit:'+event['status']
        assert g.snapshot()==frame['state']
    assert g.turn==record['turns'] and g.decisions==record['decisions']
    assert record['scores']==[g.players[record['order'].index(i)]['score'] for i in (0,1)]
    assert record['cards']==[len(g.players[record['order'].index(i)]['cards']) for i in (0,1)]
    if record['reason']=='pending_checkpoint':
        assert not g.done and g.turn==800 and record['winner'] is None
    else:
        assert g.done and g.reason==record['reason']
        winner=record['order'][1-record['frames'][-1]['event']['seat']] if g.reason.startswith('forfeit:') else (None if g.winner() is None else record['order'][g.winner()])
        assert winner==record['winner']

def main():
    config=json.loads((ROOT/'competition.json').read_text(encoding='utf-8'))
    h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert h(ROOT/'data/base.json')==config['data_sha256']
    for name,digest in config['referee_sha256'].items():assert h(ROOT/'arena'/name)==digest
    for p in config['participants']:assert h(ROOT/p['agent'])==p['sha256']
    for item in config['archives']:
        assert h(ROOT/item['file'])==item['sha256']
        with zipfile.ZipFile(ROOT/item['file']) as z:assert z.testzip() is None
    hashes=json.loads((ROOT/'records/original-game-sha256.json').read_text(encoding='utf-8'))
    states={};results={};count=0
    with zipfile.ZipFile(ROOT/'records/formal-750.zip') as original:
        manifest=json.loads(original.read('v2-six-way-750/manifest.json'))
        for pair in manifest['pairs']:
            for index in range(50):
                key=f'{pair["id"]}/game_{index+1:02}.json';data=original.read('v2-six-way-750/'+key)
                assert hashlib.sha256(data).hexdigest()==hashes[key]
                r=json.loads(data);assert r['seed']==config['seed_base']+index//2
                assert r['order']==([0,1] if index%2==0 else [1,0])
                assert r['names']==[config['participants'][i]['name'] for i in pair['players']]
                g=Game(r['seed'],max_turns=400);replay(g,r)
                if r['reason']=='turn_limit':states[key]=g
                results[key]=(pair['players'],{k:v for k,v in r.items() if k!='frames'})
                count+=1
            print('Verified original games:',count,flush=True)
    assert count==750 and len(states)==26
    resumed=0
    with zipfile.ZipFile(ROOT/'records/continuation-26.zip') as overtime:
        for name in overtime.namelist():
            if not name.endswith('.json') or '.checkpoint.' in name:continue
            path=Path(name)
            if not path.name.startswith('game_'):continue
            key='/'.join(path.parts[1:]);r=json.loads(overtime.read(name))
            assert r['continuation']['original_sha256']==hashes[key]
            old=results[key][1];assert r['seed']==old['seed'] and r['order']==old['order'] and r['names']==old['names']
            g=states[key];assert g.done and g.reason=='turn_limit' and g.phase=='main'
            g.done=False;g.reason=None;g.max_turns=0;replay(g,r)
            checkpoint=json.loads(overtime.read(str(path.with_name(path.stem+'.checkpoint.json')).replace('\\','/')))
            for field in ('decks','players','bank','turn','decisions','phase','done','reason'):
                assert checkpoint['game_vars'][field]==getattr(g,field)
            results[key]=(results[key][0],{k:v for k,v in r.items() if k!='frames'});resumed+=1
    assert resumed==26
    table=[dict(wins=0,losses=0,draws=0,pending=0,score_total=0) for _ in config['participants']]
    pending=0
    for people,r in results.values():
        for local,global_id in enumerate(people):
            row=table[global_id];row['score_total']+=r['scores'][local]
            if r['reason']=='pending_checkpoint':row['pending']+=1
            elif r['winner'] is None:row['draws']+=1
            elif r['winner']==local:row['wins']+=1
            else:row['losses']+=1
        pending+=r['reason']=='pending_checkpoint'
    latest=json.loads((ROOT/'records/latest-summary.json').read_text(encoding='utf-8'))
    for i,p in enumerate(config['participants']):
        expected=next(t for t in latest['standings'] if t['name']==p['name'])
        assert all(expected[k]==v for k,v in table[i].items())
        assert sum(table[i][k] for k in ('wins','losses','draws','pending'))==250
    assert pending==latest['pending']==25
    print('PASS: 750 originals + 26 continuations; 725 finished, 25 pending; source, deck states and latest standings match.')

if __name__=='__main__':main()
