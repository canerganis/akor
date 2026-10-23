"""Run a script with the network and process creation observed (tests/test_oz_manual.py, zero-token gate).

    manual_guard.py SCRIPT [ARGS...]     env MANUAL_GUARD_LOG names the file that receives one JSON line per event

Every socket connection or name lookup is refused and logged as {"network": ...}; every subprocess started by this
process is logged as {"spawn": argv}. The log is appended and closed per event, so a hard exit loses nothing. Spawns
made by a child process are not seen here, which is why the log also lists the child interpreter and script.
"""
import json
import os
import runpy
import socket
import subprocess
import sys

LOG = os.environ.get('MANUAL_GUARD_LOG')


def note(kind, value):
    if LOG:
        with open(LOG, 'a', encoding='utf-8') as out:
            out.write(json.dumps({kind: value}) + '\n')


def refuse(name):
    def blocked(*args, **kwargs):
        note('network', name)
        raise OSError('network is not available in the zero-token gate')
    return blocked


for _name in ('connect', 'connect_ex'):
    setattr(socket.socket, _name, refuse('socket.' + _name))
socket.create_connection = refuse('create_connection')
socket.getaddrinfo = refuse('getaddrinfo')

_init = subprocess.Popen.__init__


def _spawn(self, args, *a, **kw):
    note('spawn', [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])])
    _init(self, args, *a, **kw)


subprocess.Popen.__init__ = _spawn

if __name__ == '__main__':
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    runpy.run_path(script, run_name='__main__')
