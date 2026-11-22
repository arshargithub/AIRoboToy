"""Bounded authorized broker, preserving the existing loopback-only credential.

The credential and upstream destination are unchanged; the persistent local
memory service does not need a restart or credential rotation. No secret log.
"""
import json,sys
from pathlib import Path
from experiments.memory.runtime import Broker,SSD
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--project-ceiling-micro-usd',type=int);parser.add_argument('--maximum-calls',type=int,default=64);args=parser.parse_args()
    if not 0<=args.maximum_calls<=64:raise ValueError('Learning call bound cannot be widened')
    old=json.loads((SSD/'private-config/broker.json').read_text())
    if old['base_url']!='http://127.0.0.1:8790':raise ValueError('Unexpected broker destination')
    b=Broker(Path(args.directory),paid=True,maximum_usd=1,maximum_calls=args.maximum_calls,project_ceiling_micro_usd=args.project_ceiling_micro_usd)
    b.token=old['token'];b.serve()
