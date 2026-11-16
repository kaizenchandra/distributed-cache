#!/usr/bin/env python3
"""Exercise load reporting against a real local HTTP fixture, including overload and errors."""
import http.server
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path


class LoadTest(unittest.TestCase):
    def run_load(self, *options, fail=False):
        active = 0
        peak = 0
        lock = threading.Lock()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    time.sleep(.02)
                    error = fail and body['operation'] == 'GET'
                    self.send_response(503 if error else 200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'found': True}).encode())
                finally:
                    with lock:
                        active -= 1

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'results.json'
                command = ['python3', str(Path(__file__).with_name('load.py')), '--url',
                           f'http://127.0.0.1:{server.server_port}', '--keys', '1', '--warmup', '0',
                           '--read-ratio', '1', '--output', str(output), *options]
                process = subprocess.run(command, env=dict(os.environ, CACHE_CLIENT_TOKEN='fixture-token'),
                                         capture_output=True, text=True, timeout=20)
                self.assertTrue(output.exists(), process.stderr)
                self.last_peak = peak
                return process.returncode, json.loads(output.read_text())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_closed_loop_counts_real_hits(self):
        code, result = self.run_load('--requests', '8', '--workers', '2')
        self.assertEqual(0, code)
        self.assertEqual(8, result['counters']['success'])
        self.assertEqual(1, result['hit_ratio'])
        self.assertEqual(8, result['latency_bucket_upper_bounds']['GET']['count'])

    def test_overload_is_bounded_and_arrivals_are_accounted(self):
        code, result = self.run_load('--rate', '5000', '--duration', '.1', '--workers', '2')
        self.assertEqual(2, code)
        self.assertGreaterEqual(self.last_peak, 1)
        self.assertLessEqual(self.last_peak, 2)
        self.assertEqual(500, result['offered'])
        self.assertGreater(result['dropped_busy'] + result['dropped_scheduler'], 0)
        self.assertEqual(500, result['counters']['completed'] + result['dropped_busy'] + result['dropped_scheduler'])

    def test_errors_are_not_successes_or_hits(self):
        code, result = self.run_load('--requests', '4', '--workers', '2', fail=True)
        self.assertEqual(1, code)
        self.assertEqual(4, result['counters']['errors'])
        self.assertEqual(4, result['counters']['status_503'])
        self.assertEqual(0, result['counters'].get('success', 0))
        self.assertIsNone(result['hit_ratio'])


if __name__ == '__main__':
    unittest.main()
