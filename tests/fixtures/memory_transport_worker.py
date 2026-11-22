"""Controlled stdio child: no models/network/private data."""
import json
import os
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[1], 'a') as audit:
        audit.write(json.dumps(request)+'\n')
    op = request['op']
    if op == 'exit':os._exit(request.get('code', 3))
    if op == 'sleep':time.sleep(request.get('seconds', .3))
    if op == 'malformed':
        print(json.dumps({'ok': 'yes', 'result': 'bad'}), flush=True)
        continue
    if op == 'application_error':
        print(json.dumps({'ok': False, 'error': 'ValueError: Invalid audience'}), flush=True)
        continue
    if op == 'logs':print('Fixture boot log, not a response', flush=True)
    print(json.dumps({'ok': True, 'result': {'marker': request.get('marker'), 'closed': op == 'close'}}), flush=True)
    if op == 'close':break
