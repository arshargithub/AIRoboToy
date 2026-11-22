import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from tavi.mlx_final_asr import MlxFinalASR


SCRIPT = '''
import json,sys,time
print(json.dumps({'ready':True,'protocol':1,'profile':{'prompt':None}}),flush=True)
for n,line in enumerate(sys.stdin):
 r=json.loads(line)
 if n: time.sleep(DELAY)
 print(json.dumps({'id':r['id'],'text':'Paprika, hello.','confidence':{'prompt':None},'timing':{'worker_transcribe_ms':1.2}}),flush=True)
'''


class AdapterTests(unittest.TestCase):
    def adapter(self, delay):
        original = subprocess.Popen
        launches = []
        def spawn(args, **kwargs):
            launches.append((args, kwargs['env']))
            return original([sys.executable, '-u', '-c', SCRIPT.replace('DELAY', str(delay))], **kwargs)
        adapter = MlxFinalASR()
        self.addCleanup(adapter.close)
        with patch('tavi.mlx_final_asr.subprocess.Popen', spawn): adapter.prepare()
        self.assertNotIn('OPENAI_API_KEY', launches[0][1])
        return adapter

    def test_ready_warm_worker_returns_text_and_unhinted_confidence(self):
        adapter = self.adapter(0)
        result = adapter.decode(bytes(3200), time.monotonic()+1)
        self.assertEqual(result.text, 'Paprika, hello.')
        self.assertIsNone(result.confidence['prompt'])
        self.assertEqual(result.timing['worker_transcribe_ms'],1.2)
        self.assertGreaterEqual(result.timing['IPC_roundtrip_ms'],0)

    def test_deadline_kills_native_worker_and_cannot_reuse_stale_output(self):
        adapter = self.adapter(2)
        child = adapter.process
        start = time.monotonic()
        with self.assertRaises(TimeoutError): adapter.decode(bytes(3200), start+.05)
        self.assertLess(time.monotonic()-start, .5)
        self.assertIsNotNone(child.poll())
        self.assertIsNone(adapter.process)
        with self.assertRaisesRegex(ValueError, 'not ready'):
            adapter.decode(bytes(3200), time.monotonic()+1)

    def test_replaced_lease_is_rejected_before_native_submission(self):
        adapter=self.adapter(0)
        child=adapter.process
        with self.assertRaisesRegex(ValueError,'Obsolete'):
            adapter.decode(bytes(3200),time.monotonic()+1,valid=lambda:False)
        self.assertIs(adapter.process,child)
        self.assertIsNone(child.poll(),'A stale job must not kill a fresh idle worker')

    def test_mute_cancels_native_work_without_waiting_for_io_lock(self):
        adapter = self.adapter(2)
        errors = []
        def decode():
            try: adapter.decode(bytes(3200), time.monotonic()+3)
            except ValueError as error: errors.append(error)
        thread = threading.Thread(target=decode)
        thread.start()
        for _ in range(100):
            if adapter.active: break
            time.sleep(.001)
        began = time.monotonic()
        adapter.cancel()
        self.assertLess(time.monotonic()-began, .05)
        thread.join(.5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)

    def test_close_during_preparation_kills_child_and_cannot_restart(self):
        adapter=MlxFinalASR()
        original=subprocess.Popen
        spawned=threading.Event();errors=[];children=[]
        def spawn(args,**kwargs):
            child=original([sys.executable,'-u','-c','import time; time.sleep(30)'],**kwargs)
            children.append(child);spawned.set()
            return child
        def prepare():
            try:adapter.prepare()
            except ValueError as error:errors.append(error)
        with patch('tavi.mlx_final_asr.subprocess.Popen',spawn):
            thread=threading.Thread(target=prepare);thread.start()
            self.assertTrue(spawned.wait(2))
            began=time.monotonic();adapter.close()
            thread.join(1)
        self.assertLess(time.monotonic()-began,1)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(errors)
        with self.assertRaisesRegex(ValueError,'closed'):adapter.prepare()

    def test_mute_retains_idle_worker_but_close_is_terminal(self):
        adapter=self.adapter(0);child=adapter.process
        adapter.cancel()
        self.assertIsNone(child.poll())
        adapter.close()
        self.assertIsNotNone(child.poll())
        with self.assertRaisesRegex(ValueError,'closed'):adapter.prepare()


if __name__ == '__main__': unittest.main()
