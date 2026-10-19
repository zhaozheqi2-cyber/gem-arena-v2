"""Portable offline replay, with no external assets or server."""
import json
from pathlib import Path

def render(game,path):
    data=json.dumps(game,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=Path(__file__).with_name('replay.html').read_text(encoding='utf-8')
    Path(path).write_text(template.replace('__GAME_DATA__',data),encoding='utf-8')
