"""Opt-in real Docker contract tests; never silently pretend Docker was tested."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from arena.executor import Executor
from arena.game import Game

@unittest.skipUnless(os.environ.get('ARENA_DOCKER_TEST')=='1','Set ARENA_DOCKER_TEST=1 and build the image')
class DockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=subprocess.check_output(['docker','image','inspect','gem-arena-runtime:2',
            '--format','{{.Id}}'],text=True).strip()

    def run_agent(self,code,timeout=8):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            source=Path(d)/'agent.py';source.write_text(code,encoding='utf-8')
            return Executor(source,'docker',timeout,self.image).call(Game(1).observation(),None)

    def test_isolation_contract(self):
        code='''import os, socket
def choose(o,m):
    assert os.geteuid()!=0
    assert set(os.listdir('/sandbox'))=={'agent.py','worker.py'}
    assert not os.path.exists('/var/run/docker.sock')
    try:
        open('/sandbox/forbidden','w')
        raise AssertionError('writable root')
    except OSError: pass
    sock=socket.socket();sock.settimeout(.3)
    try:
        sock.connect(('1.1.1.1',443))
        raise AssertionError('network enabled')
    except OSError: pass
    finally: sock.close()
    return {'action':0,'memory':None}
'''
        self.assertEqual(self.run_agent(code)[2],'ok')

    def test_timeout_container_removed(self):
        self.assertEqual(self.run_agent('def choose(o,m):\n while True: pass',2)[2],'timeout')

    def test_memory_limit(self):
        self.assertEqual(self.run_agent("def choose(o,m):\n x=bytearray(256*1024*1024)\n return {'action':0}")[2],'crash')

if __name__=='__main__':unittest.main()
