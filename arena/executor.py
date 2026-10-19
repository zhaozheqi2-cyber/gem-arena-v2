"""Bounded JSON transport. Local mode is ONLY for trusted code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

OUTPUT_LIMIT=16384
MEMORY_LIMIT=4096

class Executor:
    def __init__(self, source, mode='local', timeout=3.0, image=None):
        self.source=Path(source).resolve()
        self.mode,self.timeout,self.image=mode,timeout,image

    def call(self, observation, memory):
        worker=Path(__file__).with_name('worker.py').resolve()
        name='gem-arena-'+uuid.uuid4().hex
        if self.mode=='docker':
            command=['docker','run','--rm','-i','--name',name,'--network','none',
                '--cpus','1','--memory','128m','--memory-swap','128m','--pids-limit','16',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--user','65534:65534',
                '--mount',f'type=bind,src={worker},dst=/sandbox/worker.py,readonly',
                '--mount',f'type=bind,src={self.source},dst=/sandbox/agent.py,readonly',
                self.image,'python','-I','-B','/sandbox/worker.py','/sandbox/agent.py']
        else:
            command=[sys.executable,'-I','-B',str(worker),str(self.source)]
        started=time.perf_counter()
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,cwd=str(self.source.parent),
            env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
        data=bytearray()
        overflow=threading.Event()
        request=json.dumps(dict(observation=observation,memory=memory)).encode()+b'\n'
        def read():
            try:
                while True:
                    chunk=proc.stdout.read(1024)
                    if not chunk:
                        break
                    if len(data)+len(chunk)>OUTPUT_LIMIT:
                        overflow.set()
                        proc.kill()
                        break
                    data.extend(chunk)
            except (OSError,ValueError):
                pass
        def write():
            try:
                proc.stdin.write(request)
                proc.stdin.close()
            except (OSError,ValueError):
                pass
        reader=threading.Thread(target=read,daemon=True)
        writer=threading.Thread(target=write,daemon=True)
        reader.start(); writer.start()
        status='ok'
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            status='timeout'
            proc.kill()
            proc.wait(timeout=5)
        finally:
            if self.mode=='docker':
                # Killing the docker client alone does not stop its container.
                subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,timeout=15)
        reader.join(timeout=1)
        writer.join(timeout=1)
        if not reader.is_alive():
            proc.stdout.close()
        if not writer.is_alive() and not proc.stdin.closed:
            proc.stdin.close()
        elapsed=(time.perf_counter()-started)*1000
        if overflow.is_set():
            status='output_limit'
        elif status=='ok' and proc.returncode:
            status='crash'
        if status!='ok':
            return None, memory, status, elapsed
        try:
            value=json.loads(bytes(data).decode('utf-8'))
            if not isinstance(value,dict) or type(value.get('action')) is not int:
                raise ValueError('action must be an integer')
            mem=value.get('memory')
            if len(json.dumps(mem,allow_nan=False).encode())>MEMORY_LIMIT:
                raise ValueError('memory too large')
            action=value['action']
            if not 0<=action<len(observation['legal_actions']):
                return action, mem, 'illegal_action', elapsed
            return action,mem,'ok',elapsed
        except (ValueError,TypeError,UnicodeError,RecursionError):
            return None,memory,'protocol_error',elapsed
