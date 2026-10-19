import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime,timezone

from .executor import Executor
from .game import Game,VERSION
from .replay import render

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def play(seed, order, executors, max_turns=400):
    game=Game(seed,max_turns=max_turns)
    frames=[dict(state=game.snapshot(),event=None)]
    memory=[None,None]
    times=[0.0,0.0]
    faults=[0,0]
    illegal=[0,0]
    winner=None
    reason=None
    turn_elapsed=0.0
    while not game.done:
        seat=game.turn%2
        who=order[seat]
        obs=game.observation()
        executor=executors[who]
        allowance=getattr(executor,'timeout',3.0)
        remaining=max(0.0,allowance-turn_elapsed/1000)
        obs['time_remaining_ms']=round(remaining*1000,3)
        obs['turn_budget_ms']=round(allowance*1000,3)
        if remaining<=0:
            action,mem,status,ms=None,memory[seat],'timeout',0.0
        else:
            if hasattr(executor,'timeout'): executor.timeout=remaining
            try: action,mem,status,ms=executor.call(obs,memory[seat])
            finally:
                if hasattr(executor,'timeout'): executor.timeout=allowance
            if status=='ok' and ms>remaining*1000: status='timeout'
        turn_elapsed+=ms
        times[who]+=ms
        event=dict(ply=game.turn+1,decision=game.decisions+1,phase=game.phase,
                   seat=seat,agent=who,status=status,elapsed_ms=round(ms,3),
                   action_index=action,action=None)
        if status!='ok':
            faults[who]+=1
            illegal[who]+=int(status=='illegal_action')
            winner=order[1-seat]
            reason='forfeit:'+status
            game.done=True
            game.reason=reason
        else:
            memory[seat]=mem
            event['action']=obs['legal_actions'][action]
            game.step(event['action'])
            if game.turn!=obs['turn']: turn_elapsed=0.0
        frames.append(dict(state=game.snapshot(),event=event))
    if reason is None:
        w=game.winner()
        winner=None if w is None else order[w]
        reason=game.reason
    scores=[0,0]
    card_counts=[0,0]
    for seat,who in enumerate(order):
        scores[who]=game.players[seat]['score']
        card_counts[who]=len(game.players[seat]['cards'])
    return dict(seed=seed,order=order,winner=winner,reason=reason,
                scores=scores,cards=card_counts,faults=faults,illegal_actions=illegal,
                elapsed_ms=[round(t,3) for t in times],turns=game.turn,
                decisions=game.decisions,max_turns=max_turns,frames=frames)

def run(args):
    if args.games<2 or args.games%2:
        raise ValueError('--games must be an even positive number (paired seats)')
    if args.timeout<=0:
        raise ValueError('--timeout must be positive')
    if args.max_turns<0 or args.max_turns%2:
        raise ValueError('--max-turns must be zero or a positive even number')
    out=Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Output directory must be empty; choose a new --out path')
    image=None
    if args.mode=='docker':
        # Resolve a mutable tag ONCE; both contestants use exactly this image ID.
        image=subprocess.check_output(['docker','image','inspect',args.image,
                                       '--format','{{.Id}}'],text=True).strip()
        subprocess.run(['docker','info'],check=True,stdout=subprocess.DEVNULL)
    out.mkdir(parents=True,exist_ok=True)
    names=[args.name_a,args.name_b]
    sources=[Path(args.a).resolve(),Path(args.b).resolve()]
    manifest=dict(schema=1,rules=VERSION,created_utc=datetime.now(timezone.utc).isoformat(),
        names=names,agent_sha256=[digest(p) for p in sources],mode=args.mode,
        image_id=image,host_python=sys.version,platform=platform.platform(),
        games=args.games,base_seed=args.seed,timeout_seconds=args.timeout,max_turns=args.max_turns,
        data_sha256=digest(Path(__file__).resolve().parents[1]/'data/base.json'),
        resource_policy='1 CPU / 128 MiB / 16 PIDs / no network / read-only mounts' if image else
                        'TRUSTED DEMO: wall timeout only; no filesystem/network/memory isolation',
        referee_sha256={p.name:digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    results=[]
    with tempfile.TemporaryDirectory(prefix='.agents-',dir=out) as staging:
        frozen=[]
        for i,source in enumerate(sources):
            folder=Path(staging)/str(i)
            folder.mkdir()
            dest=folder/'agent.py'
            shutil.copyfile(source,dest)
            if digest(dest)!=manifest['agent_sha256'][i]:
                raise RuntimeError('Submission changed while freezing')
            frozen.append(dest)
        executors=[Executor(p,args.mode,args.timeout,image) for p in frozen]
        for i in range(args.games):
            order=[0,1] if i%2==0 else [1,0]
            result=play(args.seed+i//2,order,executors,args.max_turns)
            result.update(game=i+1,names=names,rules=VERSION)
            (out/f'game_{i+1:02}.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            render(result,out/f'game_{i+1:02}.html')
            results.append({k:v for k,v in result.items() if k!='frames'})
            print(f"Game {i+1:02}: {result['scores']} winner={result['winner']} {result['reason']}",flush=True)
    summary=dict(games=args.games,names=names,
        wins=[sum(r['winner']==i for r in results) for i in range(2)],
        draws=sum(r['winner'] is None for r in results),
        mean_scores=[round(sum(r['scores'][i] for r in results)/args.games,2) for i in range(2)],
        faults=[sum(r['faults'][i] for r in results) for i in range(2)],
        illegal_actions=[sum(r['illegal_actions'][i] for r in results) for i in range(2)],
        elapsed_ms=[round(sum(r['elapsed_ms'][i] for r in results),2) for i in range(2)],
        turn_limit_games=sum(r['reason']=='turn_limit' for r in results),results=results)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    with (out/'results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerow(['game','seed','first','winner','reason','score_a','score_b',
                         'illegal_a','illegal_b','faults_a','faults_b','ms_a','ms_b','turns'])
        for r in results:
            writer.writerow([r['game'],r['seed'],names[r['order'][0]],
                'draw' if r['winner'] is None else names[r['winner']],r['reason'],
                *r['scores'],*r['illegal_actions'],*r['faults'],*r['elapsed_ms'],r['turns']])
    from html import escape
    links=''.join(f'<li><a href="game_{r["game"]:02}.html">Game {r["game"]:02}</a> — '
                  f'{r["scores"]} / {escape(r["reason"])}</li>' for r in results)
    (out/'index.html').write_text('<meta charset="utf-8"><title>Gem Arena results</title>'
        '<style>body{background:#0e1420;color:#eee;font:20px system-ui;padding:40px}a{color:#67d9ce}</style>'
        f'<h1>Gem Arena · {escape(names[0])} vs {escape(names[1])}</h1>'
        f'<p>Wins {summary["wins"]} · Draws {summary["draws"]}</p><ul>{links}</ul>',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False,indent=2))
    return summary

def main():
    parser=argparse.ArgumentParser(description='Paired, source-frozen programming tournament')
    parser.add_argument('--a',default='agents/greedy.py')
    parser.add_argument('--b',default='agents/random_bot.py')
    parser.add_argument('--name-a',default='Greedy demo')
    parser.add_argument('--name-b',default='Random demo')
    parser.add_argument('--games',type=int,default=20)
    parser.add_argument('--seed',type=int,default=1000)
    parser.add_argument('--mode',choices=['local','docker'],default='local')
    parser.add_argument('--image',default='gem-arena-runtime:2')
    parser.add_argument('--timeout',type=float,default=3.0)
    parser.add_argument('--max-turns',type=int,default=400,
                        help='safety stop in completed turns; draw on limit; 0 disables')
    parser.add_argument('--out',default='runs/demo')
    args=parser.parse_args()
    try:
        run(args)
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        parser.exit(2,f'Arena error: {e}\n')

if __name__=='__main__':
    main()
