"""Public mechanism demo: deliberately try blind and face-up reservations.

Not a contestant. Does not import the referee or any other agent file.
"""
def choose(obs,memory):
    p=obs['players'][obs['you']];actions=obs['legal_actions']
    memory=memory or {'opening':0}
    cards={c['id']:c for row in obs['market'] for c in row}
    cards.update({r['card']['id']:r['card'] for r in p['reserved']})
    if obs['phase']=='main' and memory['opening']<2:
        source='deck' if memory['opening']==0 else 'market'
        pool=[i for i,a in enumerate(actions) if a['type']=='reserve' and a['source']==source and
              (a.get('tier')==1 if source=='deck' else cards[a['card']]['tier']==1)]
        if pool:
            memory['opening']+=1
            return {'action':pool[0],'memory':memory}
    def gap(c,tokens):
        return max(0,sum(max(0,n-b-t) for n,b,t in zip(c['cost'],p['bonuses'],tokens))-tokens[5])
    def score(a):
        t=a['type']
        if t=='noble':return 100
        if t=='discard':
            after=[x-y for x,y in zip(p['tokens'],a['tokens'])]
            return -min((gap(c,after) for c in cards.values()),default=0)-a['tokens'][5]*3
        if t=='buy':
            c=cards[a['card']]
            return 100+c['points']*15+5/(p['bonuses'][c['bonus']]+1)-a['payment'][5]*.1
        if t=='take':
            after=[x+y for x,y in zip(p['tokens'],a['tokens'])]
            return max(((gap(c,p['tokens'])-gap(c,after))*4-gap(c,after) for c in cards.values()),default=0)-max(0,sum(after)-10)*2
        return -20
    return {'action':max(range(len(actions)),key=lambda i:score(actions[i])),'memory':memory}
