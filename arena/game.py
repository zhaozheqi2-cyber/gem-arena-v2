"""Two-player base Splendor. Referee never imports an agent.

Auxiliary discard/noble decisions belong to the SAME turn. Blind reservations
are private; snapshots are spectator views, observations are player views.
"""
import copy
import itertools
import json
from pathlib import Path
import random

VERSION = 'gem-arena-2.0'
COLORS = ['white', 'blue', 'green', 'red', 'black', 'gold']
TARGET = 15
MAX_TURNS = 0  # No artificial limit in the board-game rules.
SUPPLY = [4, 4, 4, 4, 4, 5]
_DATA = json.loads((Path(__file__).resolve().parents[1]/'data/base.json').read_text(encoding='utf-8'))


def catalogue():
    return copy.deepcopy(_DATA['cards'])


def noble_catalogue():
    return copy.deepcopy(_DATA['nobles'])


def bounded_vectors(limits, total):
    """All nonnegative vectors bounded componentwise, summing to total."""
    def visit(i, left, prefix):
        if i == len(limits)-1:
            if 0 <= left <= limits[i]:
                yield prefix+[left]
            return
        for n in range(min(limits[i], left)+1):
            yield from visit(i+1, left-n, prefix+[n])
    yield from visit(0, total, [])


class Game:
    def __init__(self, seed, max_turns=MAX_TURNS):
        if type(max_turns) is not int or max_turns < 0 or max_turns % 2:
            raise ValueError('max_turns must be zero or an even positive integer')
        rng = random.Random(seed)
        cards = catalogue()
        self.card_by_id = {c['id']:c for c in cards}
        self.noble_by_id = {n['id']:n for n in noble_catalogue()}
        self.decks = [[c for c in cards if c['tier']==t] for t in (1,2,3)]
        for deck in self.decks:
            rng.shuffle(deck)
        self.market = [[deck.pop() for _ in range(4)] for deck in self.decks]
        ns = noble_catalogue(); rng.shuffle(ns)
        self.nobles = ns[:3]
        self.initial_nobles = {n['id'] for n in self.nobles}
        self.bank = SUPPLY.copy()
        self.players = [dict(tokens=[0]*6, bonuses=[0]*5, score=0,
                             cards=[], reserved=[], nobles=[]) for _ in range(2)]
        self.turn = 0
        self.decisions = 0
        self.max_turns = max_turns
        self.phase = 'main'
        self.done = False
        self.reason = None
        self.end_triggered = False

    def payment_options(self, card, player):
        need = [max(0,c-b) for c,b in zip(card['cost'],player['bonuses'])]
        limits = [min(n,t) for n,t in zip(need,player['tokens'])]
        # Enumerate voluntary gold substitution as well as forced deficits.
        minimum = max(0,sum(need)-player['tokens'][5])
        for colored_total in range(sum(limits), minimum-1, -1):
            for colored in bounded_vectors(limits, colored_total):
                gold = sum(need)-colored_total
                if gold <= player['tokens'][5]:
                    yield colored+[gold]

    def eligible_nobles(self):
        p = self.players[self.turn % 2]
        return [n for n in self.nobles if all(b>=v for b,v in zip(p['bonuses'],n['requirements']))]

    def legal_actions(self):
        if self.done:
            return []
        p = self.players[self.turn % 2]
        if self.phase == 'discard':
            return [dict(type='discard',tokens=v) for v in bounded_vectors(p['tokens'],sum(p['tokens'])-10)]
        if self.phase == 'noble':
            return [dict(type='noble',noble=n['id']) for n in self.eligible_nobles()]
        actions = []
        for source, cards in [('market',[c for row in self.market for c in row]),
                              ('reserved',[r['card'] for r in p['reserved']])]:
            for c in cards:
                for pay in self.payment_options(c,p):
                    actions.append(dict(type='buy',card=c['id'],source=source,payment=pay))
        available = [i for i in range(5) if self.bank[i]]
        n = min(3,len(available))
        if n:
            for colors in itertools.combinations(available,n):
                actions.append(dict(type='take',tokens=[int(i in colors) for i in range(6)]))
        for i in range(5):
            if self.bank[i]>=4:
                actions.append(dict(type='take',tokens=[2 if j==i else 0 for j in range(6)]))
        if len(p['reserved'])<3:
            for row in self.market:
                for c in row:
                    actions.append(dict(type='reserve',source='market',card=c['id']))
            for tier,deck in enumerate(self.decks,1):
                if deck:
                    actions.append(dict(type='reserve',source='deck',tier=tier))
        # Emergency convention for a state in which no normal action exists.
        return actions or [dict(type='pass')]

    @staticmethod
    def _reservation_view(reservation, owner):
        c=reservation['card']
        if owner or reservation['public']:
            return dict(card=copy.deepcopy(c),public=reservation['public'])
        return dict(card=None,public=False,tier=c['tier'])

    def snapshot(self, viewer=None):
        players=[]
        for seat,p in enumerate(self.players):
            v={k:copy.deepcopy(value) for k,value in p.items() if k!='reserved'}
            v['reserved']=[self._reservation_view(r,viewer==seat) for r in p['reserved']]
            players.append(v)
        return copy.deepcopy(dict(version=VERSION,turn=self.turn,decisions=self.decisions,
            to_play=self.turn%2,phase=self.phase,bank=self.bank,market=self.market,
            nobles=self.nobles,players=players,deck_counts=[len(d) for d in self.decks],
            done=self.done,reason=self.reason,end_triggered=self.end_triggered,max_turns=self.max_turns))

    def observation(self):
        obs=self.snapshot(viewer=self.turn%2)
        obs.update(you=self.turn%2,target=TARGET,colors=COLORS.copy(),legal_actions=self.legal_actions())
        return obs

    def _pop_market(self, cid):
        for tier,row in enumerate(self.market):
            for index,c in enumerate(row):
                if c['id']==cid:
                    row.pop(index)
                    if self.decks[tier]: row.insert(index,self.decks[tier].pop())
                    return c
        raise AssertionError('validated market card missing')

    def _finish_turn(self):
        if self.players[self.turn%2]['score']>=TARGET:
            self.end_triggered=True
        self.turn+=1
        self.phase='main'
        if self.turn%2==0:
            if self.end_triggered:
                self.done,self.reason=True,'target'
            elif self.max_turns and self.turn>=self.max_turns:
                self.done,self.reason=True,'turn_limit'

    def _after_inventory(self):
        if self.eligible_nobles(): self.phase='noble'
        else: self._finish_turn()

    def step(self, action):
        # Exact shape and integer types, preventing True == 1 from bypassing validation.
        encoded=json.dumps(action,sort_keys=True,allow_nan=False)
        if encoded not in {json.dumps(a,sort_keys=True) for a in self.legal_actions()}:
            raise ValueError('illegal action')
        p=self.players[self.turn%2]
        kind=action['type']
        if kind=='noble':
            n=next(n for n in self.nobles if n['id']==action['noble'])
            self.nobles.remove(n);p['nobles'].append(n['id']);p['score']+=n['points']
            self._finish_turn()
        elif kind=='discard':
            for i,n in enumerate(action['tokens']):
                p['tokens'][i]-=n;self.bank[i]+=n
            self._after_inventory()
        else:
            if kind=='buy':
                if action['source']=='market': c=self._pop_market(action['card'])
                else:
                    r=next(r for r in p['reserved'] if r['card']['id']==action['card'])
                    p['reserved'].remove(r);c=r['card']
                for i,n in enumerate(action['payment']):
                    p['tokens'][i]-=n;self.bank[i]+=n
                p['score']+=c['points'];p['bonuses'][c['bonus']]+=1;p['cards'].append(c['id'])
            elif kind=='take':
                for i,n in enumerate(action['tokens']):
                    self.bank[i]-=n;p['tokens'][i]+=n
            elif kind=='reserve':
                public=action['source']=='market'
                c=self._pop_market(action['card']) if public else self.decks[action['tier']-1].pop()
                p['reserved'].append(dict(card=c,public=public))
                if self.bank[5]: self.bank[5]-=1;p['tokens'][5]+=1
            if sum(p['tokens'])>10: self.phase='discard'
            else: self._after_inventory()
        self.decisions+=1
        self.check()

    def winner(self):
        if not self.done: raise ValueError('game not finished')
        # A safety stop is a draw, never a pretend official points victory.
        if self.reason=='turn_limit': return None
        ranks=[(p['score'],-len(p['cards'])) for p in self.players]
        return None if ranks[0]==ranks[1] else int(ranks[1]>ranks[0])

    def check(self):
        for i,total in enumerate(SUPPLY):
            assert type(self.bank[i]) is int and self.bank[i]>=0
            assert self.bank[i]+sum(p['tokens'][i] for p in self.players)==total
        ids=[c['id'] for d in self.decks for c in d]+[c['id'] for row in self.market for c in row]
        nids=[n['id'] for n in self.nobles]
        for seat,p in enumerate(self.players):
            assert len(p['tokens'])==6 and all(type(n) is int and n>=0 for n in p['tokens'])
            limit=13 if self.phase=='discard' and seat==self.turn%2 else 10
            assert sum(p['tokens'])<=limit
            assert len(p['reserved'])<=3
            assert p['bonuses']==[sum(self.card_by_id[c]['bonus']==i for c in p['cards']) for i in range(5)]
            assert p['score']==sum(self.card_by_id[c]['points'] for c in p['cards'])+sum(self.noble_by_id[n]['points'] for n in p['nobles'])
            ids+=p['cards']+[r['card']['id'] for r in p['reserved']]
            nids+=p['nobles']
        assert len(ids)==90 and len(set(ids))==90 and set(ids)==set(self.card_by_id)
        assert len(nids)==3 and set(nids)==self.initial_nobles
        assert self.phase in ('main','discard','noble')
