'use client';
import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { decode, makeOperation, operations } from '../lib/protocol';
type Result = { id: number; label: string; status: number; ms: number; data: unknown; time: string };
const initialBatch = JSON.stringify([{ operation: 'SET', key: 'hello', value: 'Hello, cache!', ttlMillis: 60000 }, { operation: 'GET', key: 'hello', ttlMillis: -1 }], null, 2);
export default function Home() {
  const { data: session } = useSession();
  const isAdmin = session?.roles.includes('cache-admin');
  const [nodes, setNodes] = useState('http://node-a:8080,http://node-b:8080,http://node-c:8080');
  const [confirmAdmin, setConfirmAdmin] = useState(false);
  const [tab, setTab] = useState('operation');
  const [op, setOp] = useState('SET');
  const [key, setKey] = useState('hello');
  const [value, setValue] = useState('Hello, cache!');
  const [ttl, setTtl] = useState('-1');
  const [version, setVersion] = useState('0');
  const [batch, setBatch] = useState(initialBatch);
  const [history, setHistory] = useState<Result[]>([]);
  const [selected, setSelected] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState('Not checked');
  async function send(action: string, payload?: unknown, label = action) {
    setBusy(true); setError('');
    const start = performance.now();
    try {
      const response = await fetch('/api/cache', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
      const data = await response.json();
      const result = { id: Date.now(), label, status: response.status, ms: Math.round(performance.now() - start), data, time: new Date().toLocaleTimeString() };
      setSelected(result); setHistory(h => [result, ...h].slice(0, 50));
      if (action === 'health') setHealth(response.ok && data.status === 'UP' ? 'Healthy' : 'Unavailable');
    } catch { setError('Could not reach the local Next.js proxy.'); if (action === 'health') setHealth('Unavailable'); }
    finally { setBusy(false); }
  }
  function run() {
    try {
      if (tab === 'batch') {
        const items = JSON.parse(batch);
        if (!Array.isArray(items) || !items.length || items.length > 100) throw new Error('Provide an array of 1–100 operations.');
        const payload = items.map(item => {
          if (typeof item.key !== 'string' || (item.value !== undefined && typeof item.value !== 'string')) throw new Error('Keys and values must be text strings.');
          return makeOperation(item.operation, item.key, item.value ?? '', item.ttlMillis ?? -1, item.expectedVersion);
        });
        void send('batch', { operations: payload }, `BATCH · ${items.length} operations`);
      } else void send('operation', makeOperation(op, key, value, Number(ttl || NaN), Number(version || NaN)), `${op} · ${key}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Invalid input'); }
  }
  const data = selected?.data as { found?: boolean; value?: string; version?: number; ttlMillis?: number } | undefined;
  return <div className="shell">
    <aside><a className="brand" href="/">▧ <span>cache<span className="brand-light">lab</span></span></a><div className="workspace">LOCAL WORKSPACE</div><button className="nav active" onClick={() => setTab('operation')}>⌘ <span>Cache playground</span></button>{isAdmin && <button className="nav" disabled={busy} onClick={() => void send('topology')}>◈ <span>Inspect topology</span></button>}<div className="aside-bottom"><span className="dot"/> Distributed cache<br/><small>Java engine / Next.js console</small></div></aside>
    <main><header><span>Workspace <span className="slash">/</span> <strong>Playground</strong></span><span className="local">LOCAL DEVELOPMENT</span></header>
    <section className="heading"><div className="eyebrow">YOUR CACHE, UNDER THE MICROSCOPE</div><h1>Cache playground<span>.</span></h1><p>Write a value. Read it back. See your distributed system at work.</p></section>
    <section className="status-row"><div><span className={`dot ${health === 'Healthy' ? 'green' : ''}`}/><strong>{health}</strong><span className="muted">Gateway connection</span></div><button className="subtle" disabled={busy} onClick={() => void send('health')}>↻ Check health</button></section>
    <div className="grid"><section className="card editor"><div className="card-header"><h2>Request builder</h2><span className="badge">API v1</span></div><div className="tabs">{['operation', 'batch'].map(t => <button key={t} className={tab === t ? 'chosen' : ''} onClick={() => setTab(t)}>{t === 'operation' ? 'Single operation' : 'Batch operations'}</button>)}</div>
      <form onSubmit={e => { e.preventDefault(); run(); }}>
      {tab === 'operation' ? <><label htmlFor="op">Operation</label><select id="op" value={op} onChange={e => setOp(e.target.value)}>{operations.map(o => <option key={o}>{o}</option>)}</select><label htmlFor="key">Key <small>UTF-8 text → Base64url</small></label><input id="key" required value={key} onChange={e => setKey(e.target.value)} placeholder="e.g. user:42"/>{['SET', 'CAS'].includes(op) && <><label htmlFor="value">Value <small>UTF-8 · max 64 KiB</small></label><textarea id="value" rows={5} value={value} onChange={e => setValue(e.target.value)}/></>}{['SET', 'CAS', 'EXPIRE'].includes(op) && <><label htmlFor="ttl">Time to live <small>milliseconds</small></label><input id="ttl" type="number" required min={-1} max={31536000000} value={ttl} onChange={e => setTtl(e.target.value)}/><p className="hint">−1 = no expiry · 0 = delete immediately</p></>}{op === 'CAS' && <><label htmlFor="version">Expected version</label><input id="version" type="number" required min={0} value={version} onChange={e => setVersion(e.target.value)}/><p className="hint">Use the version from GET. Version 0 creates only if absent.</p></>}</> : <><label htmlFor="batch">Operations <small>JSON array · max 100</small></label><textarea id="batch" className="batch" rows={17} value={batch} onChange={e => setBatch(e.target.value)}/><p className="hint">Use plain text keys and values. Runs sequentially; batches are not atomic. Inspect every result before retrying.</p></>}
      {error && <p role="alert" className="error">{error}</p>}<button className="primary" disabled={busy} type="submit">{busy ? 'Waiting for gateway…' : 'Run request'} <span>↗</span></button></form></section>
    <section className="card response"><div className="card-header"><h2>Response</h2>{selected && <span className={`badge ${selected.status < 300 ? 'success' : 'failure'}`}>{selected.status} · {selected.ms} ms</span>}</div><div aria-live="polite">{!selected ? <div className="empty"><div className="empty-icon">⌁</div><h3>Ready when you are</h3><p>Run an operation to inspect its result,<br/>version, and remaining TTL.</p></div> : <div className="response-body"><p className="request-label">{selected.label}</p>{typeof data?.found === 'boolean' && <><div className="metrics"><div><small>FOUND</small><strong>{data.found ? 'Yes' : 'No'}</strong></div><div><small>VERSION</small><strong>{data.version}</strong></div><div><small>TTL</small><strong>{data.ttlMillis === -1 ? 'Permanent' : data.ttlMillis === -2 ? 'Missing' : `${data.ttlMillis} ms`}</strong></div></div>{typeof data.value === 'string' && <><label>Decoded value</label><pre>{decode(data.value)}</pre></>}</>}<label>Raw response</label><pre>{JSON.stringify(selected.data, null, 2)}</pre>{selected.status >= 500 && <p className="hint">A failed or timed-out mutation may have succeeded. Read the key before retrying.</p>}</div>}</div></section></div>
    {isAdmin && <section className="card admin-controls"><h2>Cluster administration</h2><p className="hint">Bootstrap initializes fresh legacy nodes or reconciles consensus membership. Topology changes are legacy-only and synchronously migrate data. Repair status is consensus-only.</p><div className="admin-actions"><button disabled={busy} onClick={() => void send('topology')}>Inspect topology</button><button disabled={busy} onClick={() => void send('repair')}>Repair status</button></div><label htmlFor="nodes">Legacy node URLs <small>comma-separated</small></label><input id="nodes" value={nodes} onChange={e => setNodes(e.target.value)}/><label><input type="checkbox" style={{width:'auto',marginRight:8}} checked={confirmAdmin} onChange={e => setConfirmAdmin(e.target.checked)}/>I intend to modify cluster state</label><div className="admin-actions"><button disabled={busy || !confirmAdmin} onClick={() => { setConfirmAdmin(false); void send('bootstrap', {}, 'BOOTSTRAP'); }}>Bootstrap / reconcile</button><button disabled={busy || !confirmAdmin || !nodes.trim()} onClick={() => { setConfirmAdmin(false); void send('changeTopology', { nodes: nodes.split(',').map(n => n.trim()).filter(Boolean) }, 'CHANGE TOPOLOGY'); }}>Apply legacy topology</button></div></section>}
    <section className="card history"><div className="card-header"><h2>Request history <span className="count">{history.length}</span></h2><button className="subtle" onClick={() => { setHistory([]); setSelected(null); }}>Clear history</button></div>{history.length ? <div className="table-wrap"><table><thead><tr><th>REQUEST</th><th>STATUS</th><th>DURATION</th><th>TIME</th></tr></thead><tbody>{history.map(r => <tr key={r.id}><td><button className="history-link" onClick={() => setSelected(r)}>{r.label}</button></td><td><span className={r.status < 300 ? 'ok' : 'bad'}>{r.status}</span></td><td>{r.ms} ms</td><td>{r.time}</td></tr>)}</tbody></table></div> : <p className="history-empty">Your session’s requests will appear here. Nothing has been sent yet.</p>}</section><footer>SESSION ONLY · LAST 50 REQUESTS <span>Explicit operations. Real responses.</span></footer>
    </main></div>;
}
