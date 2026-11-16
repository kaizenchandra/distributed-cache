#!/usr/bin/env python3
"""Bounded client HTTP workload. Local measurements are not distributed SLO evidence."""
import argparse
import base64
import collections
import concurrent.futures
import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


class Histogram:
    # Fixed memory; reported quantiles are bucket upper bounds (5% bucket spacing).
    def __init__(self):
        self.buckets = [0] * 512
        self.count = 0

    def add(self, milliseconds):
        index = max(0, min(511, math.ceil(math.log(max(.1, milliseconds) / .1, 1.05))))
        self.buckets[index] += 1
        self.count += 1

    def percentile(self, quantile):
        if not self.count: return None
        total = 0
        for i, count in enumerate(self.buckets):
            total += count
            if total >= math.ceil(self.count * quantile): return round(.1 * 1.05 ** i, 3)

    def summary(self):
        return dict(count=self.count, p50_ms=self.percentile(.5), p95_ms=self.percentile(.95),
                    p99_ms=self.percentile(.99))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', action='append', help='Repeat to distribute traffic across gateways')
    p.add_argument('--requests', type=int, default=1000, help='Closed-loop request count')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--rate', type=float, help='Open-loop target client arrivals/sec; overload is dropped, never queued')
    p.add_argument('--duration', type=float, default=10, help='Open-loop scheduling duration in seconds')
    p.add_argument('--read-ratio', type=float, default=.8)
    p.add_argument('--distribution', choices=['uniform', 'zipf'], default='uniform')
    p.add_argument('--keys', type=int, default=100)
    p.add_argument('--value-bytes', type=int, default=128)
    p.add_argument('--ttl-ms', type=int, default=-1)
    p.add_argument('--warmup', type=int, default=10)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if (a.requests < 1 or not 1 <= a.workers <= 256 or not 1 <= a.keys <= 100000 or
            not 0 <= a.value_bytes <= 65536 or not 0 <= a.read_ratio <= 1 or
            a.ttl_ms < -1 or a.ttl_ms > 31536000000 or a.warmup < 0 or
            not math.isfinite(a.duration) or a.duration <= 0 or
            a.rate is not None and (not math.isfinite(a.rate) or a.rate <= 0)):
        p.error('invalid workload bounds')
    token = os.environ.get('CACHE_CLIENT_TOKEN')
    if not token: p.error('export CACHE_CLIENT_TOKEN before running')
    urls = a.url or ['http://localhost:8080']
    prefix = 'load-' + uuid.uuid4().hex + ':'
    keys = [base64.urlsafe_b64encode((prefix + str(i)).encode()).decode().rstrip('=') for i in range(a.keys)]
    value = base64.b64encode(b'x' * a.value_bytes).decode()
    cumulative = []
    weight = 0
    for i in range(a.keys):
        weight += 1 / (i + 1) ** 1.1
        cumulative.append(weight)

    def call(kind, key, index):
        body = dict(operation=kind, key=key, ttlMillis=a.ttl_ms)
        if kind == 'SET': body['value'] = value
        req = urllib.request.Request(urls[index % len(urls)].rstrip('/') + '/api/v1/operation',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
            if not isinstance(result.get('found'), bool): raise ValueError('invalid cache response')
            return result

    # Prime real hits. Any seed failure aborts rather than mislabeling an empty cache hit-heavy.
    for index, key in enumerate(keys): call('SET', key, index)
    for i in range(a.warmup): call('GET', keys[i % len(keys)], i)
    lock = threading.Lock()
    counters = collections.Counter()
    histograms = {kind: Histogram() for kind in ['GET', 'SET', 'errors']}
    slots = threading.BoundedSemaphore(a.workers)
    next_index = 0
    started = time.perf_counter()

    def request(index):
        rng = random.Random(a.seed + index)
        kind = 'GET' if rng.random() < a.read_ratio else 'SET'
        key = keys[rng.randrange(a.keys)] if a.distribution == 'uniform' else rng.choices(keys, cum_weights=cumulative)[
            0]
        begin = time.perf_counter()
        status = '200'
        result = None
        try:
            result = call(kind, key, index)
        except urllib.error.HTTPError as error:
            status = str(error.code)
            error.close()
        except Exception:
            status = 'transport_or_protocol_error'
        elapsed = (time.perf_counter() - begin) * 1000
        with lock:
            counters['completed'] += 1
            counters['status_' + status] += 1
            counters[kind + '_completed'] += 1
            if status == '200':
                counters['success'] += 1
                histograms[kind].add(elapsed)
                if kind == 'GET': counters['hits' if result['found'] else 'misses'] += 1
            else:
                counters['errors'] += 1
                counters[kind + '_errors'] += 1
                histograms['errors'].add(elapsed)

    def bounded_request(index):
        try:
            request(index)
        finally:
            slots.release()

    def closed_worker():
        nonlocal next_index
        while True:
            with lock:
                if next_index >= a.requests: return
                index = next_index
                next_index += 1
            request(index)

    offered = a.requests
    dropped_busy = dropped_scheduler = 0
    with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:
        if a.rate is None:
            futures = [pool.submit(closed_worker) for _ in range(a.workers)]
            for future in futures: future.result()
        else:
            offered = int(a.rate * a.duration)
            index = 0
            while index < offered:
                due = started + index / a.rate
                now = time.perf_counter()
                if now < due:
                    time.sleep(min(due - now, .01))
                    continue
                # Skip late arrivals instead of converting scheduler stalls into bursts.
                late = min(offered - index - 1, max(0, int((now - due - .005) * a.rate)))
                dropped_scheduler += late
                index += late
                if slots.acquire(blocking=False):
                    pool.submit(bounded_request, index)
                else:
                    dropped_busy += 1
                index += 1
            scheduling_end = started + a.duration
            if time.perf_counter() < scheduling_end: time.sleep(scheduling_end - time.perf_counter())
    elapsed = time.perf_counter() - started
    result = dict(mode='open-loop' if a.rate else 'closed-loop', urls=urls, workers=a.workers,
                  distribution=a.distribution, keys=a.keys, value_bytes=a.value_bytes, ttl_ms=a.ttl_ms,
                  read_ratio=a.read_ratio, seed=a.seed, offered=offered, scheduled_arrivals=offered,
                  dispatched=counters['completed'], target_ops_per_second=a.rate,
                  dropped_busy=dropped_busy, dropped_scheduler=dropped_scheduler, elapsed_seconds=elapsed,
                  successful_ops_per_second=counters['success'] / elapsed, counters=dict(counters),
                  hit_ratio=counters['hits'] / (counters['hits'] + counters['misses']) if counters['hits'] + counters[
                      'misses'] else None,
                  latency_bucket_upper_bounds={kind: histogram.summary() for kind, histogram in histograms.items()},
                  note='Offered means scheduled client demand; dropped arrivals never reach the server. Client HTTP operations, priming/warmup excluded. Drain included in elapsed. No cross-host/SLO claim.')
    assert offered == counters['completed'] + dropped_busy + dropped_scheduler
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(rendered + '\n')
    if counters['errors']: raise SystemExit(1)
    if dropped_busy + dropped_scheduler: raise SystemExit(2)


if __name__ == '__main__':
    main()
