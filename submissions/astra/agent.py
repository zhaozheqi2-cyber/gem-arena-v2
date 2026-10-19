"""Codex v2: bounded public-information planning, standard library only.

No referee imports, filesystem, network, hidden catalogue or seed access.
"""
import time
from itertools import combinations
from heapq import nlargest

DEPTH = 3
WIDTH = 12
ENGINE_WEIGHT = 2.5


def choose(observation, memory):
    o = observation
    if o['version'] != 'gem-arena-2.0':
        raise ValueError('This submission requires gem-arena-2.0')
    actions = o['legal_actions']
    me, opp = o['players'][o['you']], o['players'][1-o['you']]
    remaining = max(0, o.get('time_remaining_ms', 3000))
    # Reserve most of the turn for startup, communication and auxiliary calls.
    deadline = time.perf_counter() + min(.45, max(0, (remaining-180)/1000*.22))
    cards = [c for row in o['market'] for c in row]
    market_count = len(cards)
    cards += [r['card'] for r in me['reserved'] if r.get('card') is not None]
    ids = {c['id']: i for i,c in enumerate(cards)}
    costs = [c['cost'] for c in cards]
    pts = [c['points'] for c in cards]
    colors = [c['bonus'] for c in cards]
    nobles = o['nobles']
    nids = {n['id']:i for i,n in enumerate(nobles)}
    requirements = [n['requirements'] for n in nobles]
    supply = tuple(x-y for x,y in zip((4,4,4,4,4,5),opp['tokens']))
    urgency = max(me['score'],opp['score'])
    pw = 1.85 + .045*urgency
    bw = ENGINE_WEIGHT*max(.40,1-urgency/26)
    b0 = tuple(me['bonuses'])
    initial_res = sum(1<<i for i in range(market_count,len(cards)))
    # State: tokens, bonuses, score, purchased mask, reserved mask,
    # claimed noble mask, number of opaque simulated blind reservations.
    root = (tuple(me['tokens']),b0,me['score'],0,initial_res,0,0)
    cache = {}

    def noble_gap(b,req):
        return sum(max(0,r-x) for r,x in zip(req,b))

    def value(s):
        if s in cache:
            return cache[s]
        t,b,score,bought,res,claimed,blind = s
        v = pw*(score-me['score'])
        v += bw*sum(sum(1/(1+.45*k) for k in range(b0[j],b[j])) for j in range(5))
        np = sorted((3*pw*.71**noble_gap(b,req) for k,req in enumerate(requirements)
                     if not claimed>>k&1),reverse=True)
        v += sum(x*w for x,w in zip(np,(.65,.25,.12)))
        potentials=[]
        demand=[0.0]*5
        for i,cost in enumerate(costs):
            if bought>>i&1:
                continue
            pay=[max(0,cost[j]-b[j]) for j in range(5)]
            missing=[max(0,pay[j]-t[j]) for j in range(5)]
            # Spend flexible gold on the largest bottleneck first.
            left=missing[:]
            for _ in range(t[5]):
                j=max(range(5),key=lambda j:left[j])
                if left[j]: left[j]-=1
            gap=sum(left)
            steps=max(max(left),gap/2.5)
            impossible=sum(max(0,pay[j]-supply[j]) for j in range(5))
            if impossible>t[5]: steps+=(impossible-t[5])*1.5
            steps+=max(0,sum(pay)-10)*1.5
            gain=pw*pts[i]+bw/(1+.45*b[colors[i]])
            for k,req in enumerate(requirements):
                if not claimed>>k&1 and b[colors[i]]<req[colors[i]]:
                    d=noble_gap(b,req)
                    gain+=1.5*pw*(.71**(d-1)-.71**d)
            potentials.append(gain/(1+steps)**1.45)
            for j in range(5):
                demand[j]=max(demand[j],min(t[j],pay[j])*.18/(1+steps))
        potentials.sort(reverse=True)
        v+=.62*sum(x*w for x,w in zip(potentials,(1,.28,.10)))
        v+=sum(demand)+.025*sum(t[:5])+.55*t[5]
        # Reserving is useful only if it yields gold, secures a target or denies one.
        v-=.15*(res.bit_count()+blind)
        cache[s]=v
        return v

    def trim(s):
        # Greedy marginal trimming is bounded (at most three coins); real discard
        # phase below evaluates every provided legal combination exactly.
        while sum(s[0])>10:
            options=[]
            for j,t in enumerate(s[0]):
                if t:
                    nt=tuple(x-int(k==j) for k,x in enumerate(s[0]))
                    ns=(nt,)+s[1:]
                    options.append(ns)
            s=max(options,key=value)
        return s

    def finish(s):
        s=trim(s)
        eligible=[k for k,req in enumerate(requirements) if not s[5]>>k&1 and noble_gap(s[1],req)==0]
        if eligible:
            # Take the noble the opponent is closest to, leaving alternatives.
            k=min(eligible,key=lambda k:noble_gap(opp['bonuses'],requirements[k]))
            s=(s[0],s[1],s[2]+nobles[k]['points'],s[3],s[4],s[5]|(1<<k),s[6])
        return s

    if o['phase']=='noble':
        index=min(range(len(actions)),key=lambda i:noble_gap(opp['bonuses'],requirements[nids[actions[i]['noble']]]))
        return {'action':index,'memory':None}
    if o['phase']=='discard':
        best=(-float('inf'),0)
        for index,a in enumerate(actions):
            nt=tuple(t-d for t,d in zip(root[0],a['tokens']))
            score=value((nt,)+root[1:])
            best=max(best,(score,-index))
        return {'action':-best[1],'memory':None}

    def apply(s,a):
        t,b,score,bought,res,claimed,blind=s
        kind=a['type']
        if kind=='buy':
            i=ids[a['card']]
            t=tuple(x-y for x,y in zip(t,a['payment']))
            b=tuple(x+int(j==colors[i]) for j,x in enumerate(b))
            score+=pts[i]; bought|=1<<i; res&=~(1<<i)
        elif kind=='take':
            t=tuple(x+y for x,y in zip(t,a['tokens']))
        elif kind=='reserve':
            if a['source']=='market': res|=1<<ids[a['card']]
            else: blind+=1
            if supply[5]>t[5]: t=t[:5]+(t[5]+1,)
        return finish((t,b,score,bought,res,claimed,blind))

    def moves(s):
        t,b,score,bought,res,claimed,blind=s
        for i,cost in enumerate(costs):
            if bought>>i&1: continue
            pay=tuple(min(t[j],max(0,cost[j]-b[j])) for j in range(5))
            gold=sum(max(0,cost[j]-b[j])-pay[j] for j in range(5))
            if gold<=t[5]:
                yield {'type':'buy','card':cards[i]['id'],'payment':pay+(gold,)}
        available=[j for j in range(5) if supply[j]>t[j]]
        n=min(3,len(available))
        if n:
            for subset in combinations(available,n):
                yield {'type':'take','tokens':tuple(int(j in subset) for j in range(6))}
        for j in range(5):
            if supply[j]-t[j]>=4:
                yield {'type':'take','tokens':tuple(2*int(k==j) for k in range(6))}
        if res.bit_count()+blind<3 and supply[5]>t[5]:
            candidates=[i for i in range(market_count) if not (bought|res)>>i&1]
            def reserve_key(i):
                missing=sum(max(0,costs[i][j]-b[j]-t[j]) for j in range(5))-t[5]
                return (pw*pts[i]+bw)/(2+max(0,missing))
            for i in nlargest(3,candidates,key=reserve_key):
                yield {'type':'reserve','source':'market','card':cards[i]['id']}

    # Enumerate opponent's visible, immediately affordable replies for terminal
    # defense. Unknown opponent reservations and unknown replenishments stay unknown.
    opponent_cards=[c for row in o['market'] for c in row]
    opponent_cards += [r['card'] for r in opp['reserved'] if r.get('card') is not None]
    affordable=[]
    for c in opponent_cards:
        if sum(max(0,c['cost'][j]-opp['bonuses'][j]-opp['tokens'][j]) for j in range(5))<=opp['tokens'][5]:
            b=tuple(x+int(j==c['bonus']) for j,x in enumerate(opp['bonuses']))
            affordable.append((c,b))

    def opponent_rank(s):
        removed=s[3]|(s[4]&~initial_res)
        def noble_points(b):
            return max([nobles[k]['points'] for k,req in enumerate(requirements)
                        if not s[5]>>k&1 and noble_gap(b,req)==0] or [0])
        best=(opp['score']+noble_points(opp['bonuses']),-len(opp['cards']))
        for c,b in affordable:
            if c['id'] in ids and removed>>ids[c['id']]&1: continue
            best=max(best,(opp['score']+c['points']+noble_points(b),-len(opp['cards'])-1))
        return best

    last=o['you']==1 and o['end_triggered']
    base=value(root)
    beam=[]; best=(-float('inf'),0)
    old_opp=opponent_rank(root)
    for index,a in enumerate(actions):
        s=apply(root,a)
        mine=(s[2],-len(me['cards'])-s[3].bit_count())
        if last:
            v=mine[0]*100+mine[1]
        else:
            v=value(s)-base
            reply=opponent_rank(s)
            v+=.22*(old_opp[0]-reply[0])
            if a['type']=='reserve' and a['source']=='deck': v-=.6
            if s[2]>=o['target']:
                other=reply if o['you']==0 else (opp['score'],-len(opp['cards']))
                v+=1000 if mine>other else (100 if mine==other else -200)
            elif reply[0]>=o['target']:
                # Opponent seat 1 ends the round immediately; seat 0 leaves us
                # a final response, so use a smaller warning in that case.
                v-=120 if o['you']==0 else 8
        best=max(best,(v,-index))
        beam.append((v,index,s,v))
    if last or best[0]>500 or remaining<350:
        return {'action':-best[1],'memory':None}
    beam=nlargest(WIDTH,beam,key=lambda x:x[0])
    for depth in range(1,DEPTH):
        candidates={}
        for _,first,s,path in beam:
            if time.perf_counter()>deadline:
                return {'action':-best[1],'memory':None}
            if s[2]>=o['target']: continue
            old=value(s)
            for a in moves(s):
                ns=apply(s,a)
                v=path+.85**depth*(value(ns)-old)-.035
                if ns[2]>=o['target']: v+=25*.85**depth
                if ns not in candidates or v>candidates[ns][0]:
                    candidates[ns]=(v,first,ns,v)
                best=max(best,(v,-first))
        if not candidates: break
        beam=nlargest(WIDTH,candidates.values(),key=lambda x:x[0])
    return {'action':-best[1],'memory':None}
