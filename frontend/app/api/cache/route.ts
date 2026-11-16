import { NextRequest, NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
export const runtime = 'nodejs';
const routes = {
  operation: { path: '/api/v1/operation', method: 'POST', role: 'CLIENT' },
  batch: { path: '/api/v1/cache/batch', method: 'POST', role: 'CLIENT' },
  health: { path: '/actuator/health', method: 'GET', role: '' },
  bootstrap: { path: '/admin/bootstrap', method: 'POST', role: 'ADMIN' },
  changeTopology: { path: '/admin/topology', method: 'POST', role: 'ADMIN' },
  repair: { path: '/admin/repair', method: 'GET', role: 'ADMIN' },
  topology: { path: '/admin/topology', method: 'GET', role: 'ADMIN' },
} as const;
export async function POST(request: NextRequest) {
  const origin = request.headers.get('origin');
  const expectedOrigin = new URL(process.env.NEXTAUTH_URL || request.nextUrl.origin).origin;
  if (origin && origin !== expectedOrigin) return NextResponse.json({ error: 'Cross-origin requests rejected' }, { status: 403 });
  try {
    const session = await getToken({ req: request, secret: process.env.NEXTAUTH_SECRET });
    if (!session?.accessToken || !session.accessExpires || Date.now() >= session.accessExpires * 1000)
      return NextResponse.json({ error: 'Sign in with Keycloak; your session may have expired.' }, { status: 401 });
    const input = await request.text();
    if (Buffer.byteLength(input) > 110000) return NextResponse.json({ error: 'Request too large' }, { status: 413 });
    const { action, payload } = JSON.parse(input);
    if (!Object.hasOwn(routes, action)) return NextResponse.json({ error: 'Unknown action' }, { status: 400 });
    const route = routes[action as keyof typeof routes];
    const roles = session.roles || [];
    if (!(roles.includes('cache-admin') || route.role !== 'ADMIN' && roles.includes('cache-user')))
      return NextResponse.json({ error: 'Your account does not have the required cache role.' }, { status: 403 });
    const token = session.accessToken;
    const body = route.method === 'POST' ? JSON.stringify(payload) : undefined;
    if (body && Buffer.byteLength(body) > 100000) return NextResponse.json({ error: 'Backend request exceeds 100,000 bytes' }, { status: 413 });
    const response = await fetch(new URL(route.path, process.env.CACHE_API_URL || 'http://localhost:8080'), {
      method: route.method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body, cache: 'no-store', signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    const raw = await response.text();
    let data; try { data = JSON.parse(raw); } catch { data = { message: raw || response.statusText }; }
    return NextResponse.json(data, { status: response.status, headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    if (error instanceof SyntaxError) return NextResponse.json({ error: 'Invalid JSON request' }, { status: 400 });
    return NextResponse.json({ error: 'Gateway unreachable or request timed out. Check CACHE_API_URL and the backend. A timed-out write may have succeeded; read before retrying.' }, { status: 502 });
  }
}
