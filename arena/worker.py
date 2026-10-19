"""One request per process. Runs inside the selected execution boundary."""
import importlib.util
import json
import sys

def main():
    request=json.loads(sys.stdin.readline())
    spec=importlib.util.spec_from_file_location('submission',sys.argv[1])
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result=module.choose(request['observation'],request.get('memory'))
    print(json.dumps(result,allow_nan=False,separators=(',',':')),flush=True)

if __name__=='__main__':
    main()
