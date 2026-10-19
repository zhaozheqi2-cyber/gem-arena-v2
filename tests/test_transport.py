import unittest
import tempfile
from pathlib import Path
from arena.game import Game
from arena.executor import Executor
from arena.tournament import play

class TransportTests(unittest.TestCase):
    def execute(self,code,timeout=2):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            p=Path(d)/'agent.py';p.write_text(code,encoding='utf-8')
            return Executor(p,timeout=timeout).call(Game(1).observation(),None)

    def test_valid(self):
        a,m,s,t=self.execute("def choose(o,m): return {'action':0,'memory':{'ok':1}}")
        self.assertEqual((a,m,s),(0,{'ok':1},'ok'))
        self.assertGreater(t,0)

    def test_illegal(self):
        self.assertEqual(self.execute("def choose(o,m): return {'action':-1}")[2],'illegal_action')

    def test_bad_json_boolean_and_memory(self):
        for code in ["def choose(o,m): return {'action':True}",
                     "def choose(o,m): return {'action':0,'memory':'x'*5000}",
                     "print('debug')\ndef choose(o,m): return {'action':0}"]:
            self.assertEqual(self.execute(code)[2],'protocol_error')

    def test_crash(self):
        self.assertEqual(self.execute("raise RuntimeError('bad')")[2],'crash')

    def test_timeout(self):
        self.assertEqual(self.execute("def choose(o,m):\n while True: pass",.2)[2],'timeout')

    def test_output_limit(self):
        self.assertEqual(self.execute("def choose(o,m):\n print('x'*20000)\n return {'action':0}")[2],'output_limit')

    def test_forfeit_seat_mapping(self):
        class Invalid:
            def call(self,o,m):return -1,None,'illegal_action',1
        r=play(1,[1,0],[Invalid(),Invalid()])
        self.assertEqual(r['winner'],0)
        self.assertEqual(r['illegal_actions'],[0,1])
        self.assertEqual(r['faults'],[0,1])
        self.assertEqual(r['reason'],'forfeit:illegal_action')

if __name__=='__main__':unittest.main()
