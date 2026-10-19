import copy
import importlib.util
import json
from pathlib import Path
import random
import unittest
from arena.game import Game, catalogue, noble_catalogue, SUPPLY
from arena.tournament import play

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('baseline',ROOT/'agents/greedy.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)

def grant_tokens(g,seat,counts):
    for i,n in enumerate(counts):
        g.bank[i]+=g.players[seat]['tokens'][i]-n
    g.players[seat]['tokens']=counts.copy()

def grant_card(g,seat,cid):
    p=g.players[seat]
    for row in g.market+g.decks:
        for c in row:
            if c['id']==cid:
                row.remove(c)
                p['cards'].append(cid);p['bonuses'][c['bonus']]+=1;p['score']+=c['points']
                return
    raise AssertionError(cid)

def grant_bonuses(g,seat,wanted):
    p=g.players[seat]
    for bonus,n in enumerate(wanted):
        available=sorted([c for row in g.market+g.decks for c in row if c['bonus']==bonus],key=lambda c:c['points'])
        for c in available[:max(0,n-p['bonuses'][bonus])]: grant_card(g,seat,c['id'])

class RulesTests(unittest.TestCase):
    def test_real_deck_setup(self):
        cards=catalogue();ns=noble_catalogue();g=Game(12)
        self.assertEqual([sum(c['tier']==t for c in cards) for t in (1,2,3)],[40,30,20])
        self.assertEqual(len(ns),10);self.assertTrue(all(n['points']==3 for n in ns))
        self.assertEqual([len(d) for d in g.decks],[36,26,16])
        self.assertEqual(g.bank,[4,4,4,4,4,5]);self.assertEqual(len(g.nobles),3)
        self.assertEqual(g.snapshot(),Game(12).snapshot());g.check()

    def test_take_double_and_short_supply(self):
        g=Game(1)
        self.assertEqual(sum(a['type']=='take' for a in g.legal_actions()),15)
        g.step(dict(type='take',tokens=[2,0,0,0,0,0]))
        self.assertFalse(any(a.get('tokens')==[2,0,0,0,0,0] for a in g.legal_actions()))
        grant_tokens(g,0,[4,4,2,0,0,0]);grant_tokens(g,1,[0,0,2,4,0,0])
        takes=[a for a in g.legal_actions() if a['type']=='take']
        self.assertIn(dict(type='take',tokens=[0,0,0,0,1,0]),takes)
        self.assertFalse(any(a['tokens'][5] for a in takes))

    def test_overflow_is_same_turn_and_can_return_gold(self):
        g=Game(1);grant_tokens(g,0,[4,4,2,0,0,0]);g.check()
        a=next(a for a in g.legal_actions() if a['type']=='reserve')
        g.step(a)
        self.assertEqual((g.turn,g.phase,sum(g.players[0]['tokens'])),(0,'discard',11))
        discards=g.legal_actions();self.assertTrue(all(a['type']=='discard' for a in discards))
        self.assertIn(dict(type='discard',tokens=[0,0,0,0,0,1]),discards)
        g.step(dict(type='discard',tokens=[1,0,0,0,0,0]))
        self.assertEqual(g.turn,1);self.assertEqual(g.players[0]['tokens'][5],1);g.check()

    def test_take_at_ten_return_three_without_losing_turn(self):
        g=Game(2);grant_tokens(g,0,[2,2,2,2,2,0])
        g.step(dict(type='take',tokens=[1,1,1,0,0,0]))
        self.assertEqual(g.turn,0);self.assertEqual(sum(g.players[0]['tokens']),13)
        self.assertTrue(all(sum(a['tokens'])==3 for a in g.legal_actions()))
        g.step(dict(type='discard',tokens=[0,0,0,1,2,0]))
        self.assertEqual(g.turn,1);g.check()

    def test_reserve_public_blind_private_and_limit(self):
        g=Game(9);cid=g.decks[0][-1]['id'];before=len(g.decks[0])
        g.step(dict(type='reserve',source='deck',tier=1))
        self.assertEqual(len(g.decks[0]),before-1)
        r=g.observation()['players'][0]['reserved'][0]
        self.assertEqual(r,dict(card=None,public=False,tier=1))
        self.assertNotIn(cid,json.dumps(g.snapshot()['players'][0]['reserved']))
        g.step(dict(type='reserve',source='deck',tier=2))
        self.assertEqual(g.observation()['players'][0]['reserved'][0]['card']['id'],cid)
        g.step(dict(type='reserve',source='deck',tier=1))
        g.step(dict(type='reserve',source='deck',tier=2))
        a=next(a for a in g.legal_actions() if a['type']=='reserve' and a['source']=='market')
        visible=a['card'];tier=g.card_by_id[visible]['tier']-1;before=len(g.decks[tier])
        g.step(a)
        self.assertEqual(len(g.decks[tier]),before-1)
        self.assertEqual(g.observation()['players'][0]['reserved'][-1]['card']['id'],visible)
        # Bank gold is now empty, but the other player can still reserve.
        self.assertEqual(g.bank[5],0)
        g.step(dict(type='reserve',source='deck',tier=2))
        self.assertFalse(any(a['type']=='reserve' for a in g.legal_actions()))
        self.assertEqual(len(g.players[1]['reserved']),3);g.check()

    def test_gold_all_payments_including_voluntary_substitution(self):
        g=Game(1)
        p=dict(tokens=[2,1,0,0,0,3],bonuses=[1,0,0,0,0])
        card=dict(cost=[3,1,0,0,0])
        payments=list(g.payment_options(card,p))
        self.assertIn([2,1,0,0,0,0],payments)
        self.assertIn([1,1,0,0,0,1],payments)
        self.assertIn([0,0,0,0,0,3],payments)
        p['tokens']=[0]*6
        self.assertEqual(list(g.payment_options(card,p)),[])

    def test_buy_reserved_returns_gold_and_counts_discount(self):
        g=Game(1);g.step(dict(type='reserve',source='deck',tier=1))
        # Let opponent act, then grant legitimate owned discounts to buyer.
        g.step(dict(type='take',tokens=[1,1,1,0,0,0]))
        c=g.players[0]['reserved'][0]['card']
        grant_bonuses(g,0,c['cost']);g.check()
        before=g.players[0]['score'];gold=g.players[0]['tokens'][5]
        buy=next(a for a in g.legal_actions() if a['type']=='buy' and a['source']=='reserved')
        g.step(buy)
        self.assertEqual(len(g.players[0]['reserved']),0)
        self.assertEqual(g.players[0]['score'],before+c['points'])
        self.assertEqual(g.players[0]['tokens'][5],gold)

    def test_buy_with_gold_spends_back_to_bank(self):
        g=Game(2)
        c=next(c for row in g.market for c in row if c['tier']==1 and sum(c['cost'])<=5)
        grant_tokens(g,0,[0,0,0,0,0,5])
        buy=next(a for a in g.legal_actions() if a['type']=='buy' and a['card']==c['id'])
        old_bank=g.bank[5];g.step(buy)
        self.assertEqual(g.bank[5],old_bank+sum(c['cost']))
        self.assertIn(c['id'],g.players[0]['cards']);g.check()

    def test_noble_mandatory_choice_one_each_turn_no_spending(self):
        g=Game(5)
        wanted=[max(n['requirements'][i] for n in g.nobles) for i in range(5)]
        grant_bonuses(g,0,wanted);g.check();before=g.players[0]['score'];bonus=g.players[0]['bonuses'].copy()
        g.step(next(a for a in g.legal_actions() if a['type']=='take'))
        self.assertEqual((g.turn,g.phase),(0,'noble'))
        self.assertEqual(len(g.legal_actions()),3)
        g.step(g.legal_actions()[1])
        self.assertEqual(g.turn,1);self.assertEqual(len(g.players[0]['nobles']),1)
        self.assertEqual(len(g.nobles),2);self.assertEqual(g.players[0]['score'],before+3)
        self.assertEqual(g.players[0]['bonuses'],bonus);g.check()

    def test_final_round_noble_trigger_and_tiebreak(self):
        g=Game(5);n=g.nobles[0];grant_bonuses(g,0,n['requirements'])
        # Raise actual development-card points to at least 12.
        for c in sorted([c for row in g.decks+g.market for c in row],key=lambda c:-c['points']):
            if g.players[0]['score']>=12: break
            grant_card(g,0,c['id'])
        g.step(next(a for a in g.legal_actions() if a['type']=='take'))
        self.assertEqual(g.phase,'noble');g.step(g.legal_actions()[0])
        self.assertFalse(g.done);self.assertTrue(g.end_triggered)
        g.step(next(a for a in g.legal_actions() if a['type']=='take'))
        self.assertTrue(g.done);self.assertEqual(g.reason,'target');self.assertEqual(g.winner(),0)
        # Pure result ranking, with nobles excluded from development card count.
        g.players[1]['score']=g.players[0]['score'];g.players[1]['cards']=g.players[0]['cards'].copy()
        self.assertIsNone(g.winner());g.players[1]['cards'].append('tie fixture');self.assertEqual(g.winner(),0)

    def test_illegal_atomic_no_arbitrary_pass_or_old_return(self):
        g=Game(1)
        for action in [dict(type='pass'),dict(type='return',color=0),dict(type='reserve',source='deck',tier=True)]:
            before=g.snapshot()
            with self.assertRaises(ValueError):g.step(action)
            self.assertEqual(before,g.snapshot())
        obs=g.observation();self.assertNotIn('seed',obs);self.assertNotIn('decks',obs)
        obs['players'][0]['tokens'][0]=99;self.assertEqual(g.players[0]['tokens'][0],0)

    def test_no_official_cap_safety_draw(self):
        self.assertEqual(Game(1).max_turns,0)
        g=Game(1,max_turns=2)
        for _ in range(2):g.step(next(a for a in g.legal_actions() if a['type']=='take'))
        self.assertEqual(g.reason,'turn_limit');self.assertIsNone(g.winner())
        self.assertEqual(g.legal_actions(),[])

    def test_deck_exhaustion_no_refill(self):
        g=Game(1)
        for c in list(g.decks[0]):grant_card(g,1,c['id'])
        g.check();a=next(a for a in g.legal_actions() if a['type']=='reserve' and a['source']=='market' and g.card_by_id[a['card']]['tier']==1)
        g.step(a);self.assertEqual(len(g.market[0]),3);g.check()

    def test_random_invariants_and_deterministic_replay(self):
        counts={};terminal=0
        for seed in range(20):
            g=Game(seed,max_turns=160);h=Game(seed,max_turns=160);rng=random.Random(seed)
            while not g.done:
                acts=g.legal_actions();a=rng.choice(acts)
                counts[a['type']]=counts.get(a['type'],0)+1
                g.step(a);h.step(copy.deepcopy(a));self.assertEqual(g.snapshot(),h.snapshot())
            terminal+=1
        self.assertEqual(terminal,20)
        for kind in ('take','buy','reserve','discard'):self.assertIn(kind,counts)

    def test_baseline_games_and_auxiliary_turn_seat_mapping(self):
        class Inline:
            def call(self,o,m):
                r=baseline.choose(o,m);return r['action'],r['memory'],'ok',0.1
        for seed in range(4):
            r=play(seed,[1,0],[Inline(),Inline()],max_turns=400)
            self.assertEqual(r['faults'],[0,0]);self.assertEqual(r['reason'],'target')
            for prev,nxt in zip(r['frames'],r['frames'][1:]):
                e=nxt['event']
                self.assertEqual(e['seat'],prev['state']['to_play'])
                if nxt['state']['phase'] in ('discard','noble'):
                    self.assertEqual(prev['state']['turn'],nxt['state']['turn'])
        class Invalid:
            def call(self,o,m):return -1,None,'illegal_action',1
        r=play(1,[1,0],[Invalid(),Invalid()])
        self.assertEqual(r['winner'],0);self.assertEqual(r['faults'],[0,1])

    def test_timeout_budget_shared_by_same_turn_choices(self):
        class Slow:
            timeout=3.0
            def __init__(self):self.calls=[]
            def call(self,o,m):
                self.calls.append(o['time_remaining_ms'])
                if o['phase']=='main':
                    reserve=next((i for i,a in enumerate(o['legal_actions']) if a['type']=='reserve'),None)
                    take=next((i for i,a in enumerate(o['legal_actions']) if a['type']=='take'),0)
                    return reserve if reserve is not None else take,None,'ok',2100
                return 0,None,'ok',2100
        a=Slow();b=Slow();r=play(1,[0,1],[a,b],max_turns=40)
        self.assertEqual(r['reason'],'forfeit:timeout')
        self.assertTrue(any(x<3000 for x in a.calls+b.calls))

if __name__=='__main__':unittest.main()
