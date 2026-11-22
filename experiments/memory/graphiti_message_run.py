"""Explicit entrypoint for the prospectively declared Graphiti message variant."""
import argparse
from experiments.memory.pilot import Process

class ConversationProcess(Process):
    def __init__(self,engine,directory,logs,entrypoint='qualification_worker.py'):
        if engine!='graphiti':raise ValueError('Message variant requires Graphiti only')
        super().__init__(engine,directory,logs,'graphiti_conversation_worker.py')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['screen','e5']);p.add_argument('protocol');a=p.parse_args()
    if a.mode=='screen':from experiments.memory import qualification_screen as runner
    else:from experiments.memory import e5_runner as runner
    runner.Process=ConversationProcess
    runner.run(a.protocol)
