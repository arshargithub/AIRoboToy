"""Replay only the fixed synthetic fixture through an already running local server."""
import argparse
from http.client import HTTPConnection
import json
from pathlib import Path
import time
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--mode', choices=('both', 'hinted', 'unhinted'), default='both')
    args = parser.parse_args()
    with wave.open('.tavi/audio/paprika-reference.wav') as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
        raw = source.readframes(source.getnframes())
    raw = bytes(16000) + raw + bytes(48000)
    raw += bytes(-len(raw) % 1024)

    def request(path, data=b'', headers=None):
        connection = HTTPConnection('127.0.0.1', args.port, timeout=25)
        try:
            connection.request('POST', path, body=data, headers=headers or {})
            response = connection.getresponse()
            value = json.loads(response.read())
            assert response.status == 200, (response.status, value)
            return value
        finally:
            connection.close()

    results = []
    for mode in ('hinted', 'unhinted') if args.mode == 'both' else (args.mode,):
        lease = request('/api/live-wake/start', json.dumps({'mode': mode}), {'Content-Type': 'application/json'})['stream_id']
        events, round_trips = [], []
        connection = HTTPConnection('127.0.0.1', args.port, timeout=2)
        started = time.perf_counter()
        try:
            for seq, offset in enumerate(range(0, len(raw), 1024)):
                wait = started + seq * .032 - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                before = time.perf_counter()
                connection.request('POST', '/api/live-wake/frame', body=raw[offset:offset + 1024], headers={
                    'Content-Type': 'application/octet-stream', 'X-Audio-Stream': lease, 'X-Audio-Sequence': str(seq)})
                response = connection.getresponse()
                value = json.loads(response.read())
                assert response.status == 200, (response.status, value)
                round_trips.append((time.perf_counter() - before) * 1000)
                events.extend(value['events'])
        finally:
            connection.close()
            request('/api/live-wake/stop', headers={'X-Audio-Stream': lease})
        recognition = [e for e in events if e['type'] == 'recognition']
        finals = [e for e in recognition if e['final']]
        assert finals and len(finals[-1]['text']) > 80, 'Expected the full synthetic turn, not just its name prefix'
        assert sum(e['first_detection'] for e in recognition) == 1
        sorted_rtt = sorted(round_trips)
        result = {'mode': mode, 'frames': len(round_trips), 'rtt_p95_ms': sorted_rtt[int(.95 * (len(sorted_rtt) - 1))],
                  'rtt_max_ms': max(round_trips), 'recognition_jobs': len(recognition),
                  'incremental_detection': any(e['first_detection'] and not e['final'] for e in recognition),
                  'final_word_count': len(finals[-1]['text'].split()),
                  'final_snapshot_end_sample': finals[-1]['snapshot_end_sample'],
                  'decode_ms': [e['decode_ms'] for e in recognition]}
        results.append(result)
        print(json.dumps(result), flush=True)
    out = Path('.tavi/live-smoke-result.json')
    out.write_text(json.dumps({'scope': 'Digital synthetic replay only; not microphone, AEC or acoustic latency acceptance',
                               'fixture': 'paprika-reference.wav from tavi.setup_live_wake', 'results': results,
                               'api_spend_usd': 0}, indent=2) + '\n')


if __name__ == '__main__': main()
