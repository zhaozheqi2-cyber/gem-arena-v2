"""Public v2 teaching baseline, not a contestant or an optimal strategy."""

def choose(obs, memory):
    if obs['version']!='gem-arena-2.0': raise ValueError('v2 agent only')
    p=obs['players'][obs['you']]
    actions=obs['legal_actions']
    cards={c['id']:c for row in obs['market'] for c in row}
    cards.update({r['card']['id']:r['card'] for r in p['reserved']})
    def gap(c,tokens):
        missing=sum(max(0,n-b-t) for n,b,t in zip(c['cost'],p['bonuses'],tokens))
        return max(0,missing-tokens[5])
    def noble_progress(bonus):
        best=0
        for n in obs['nobles']:
            before=sum(max(0,r-b) for r,b in zip(n['requirements'],p['bonuses']))
            after=sum(max(0,r-b-int(i==bonus)) for i,(r,b) in enumerate(zip(n['requirements'],p['bonuses'])))
            best=max(best,(before-after)*8/(after+1))
        return best
    def score(a):
        kind=a['type']
        if kind=='noble': return 100
        if kind=='discard':
            remaining=[t-n for t,n in zip(p['tokens'],a['tokens'])]
            targets=sorted((gap(c,remaining) for c in cards.values()))[:3]
            return -sum(targets)-a['tokens'][5]*3
        if kind=='buy':
            c=cards[a['card']]
            return 30+c['points']*12+noble_progress(c['bonus'])+4/(1+p['bonuses'][c['bonus']])-a['payment'][5]*.4-sum(a['payment'])*.05
        if kind=='take':
            after=[t+n for t,n in zip(p['tokens'],a['tokens'])]
            return max(((gap(c,p['tokens'])-gap(c,after))*4-gap(c,after)*1.5+c['points'] for c in cards.values()),default=0)-max(0,sum(after)-10)*2
        if kind=='reserve':
            gold=int(obs['bank'][5]>0)
            if a['source']=='deck': return -5+gold*2
            c=cards[a['card']]
            return -2+c['points']*1.3-gap(c,p['tokens'])+gold*3-len(p['reserved'])*2
        return -100
    return {'action':max(range(len(actions)),key=lambda i:score(actions[i])),'memory':None}
