"""Reproducible public random baseline with a preference for purchases."""
import random
def choose(obs,memory):
    rng=random.Random((memory or 0)+7919+obs['turn'])
    actions=obs['legal_actions']
    buys=[i for i,a in enumerate(actions) if a['type']=='buy']
    takes=[i for i,a in enumerate(actions) if a['type']=='take']
    pool=buys or takes or list(range(len(actions)))
    return {'action':rng.choice(pool),'memory':rng.randrange(2**30)}
