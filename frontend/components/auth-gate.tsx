'use client';
import {SessionProvider, signIn, signOut, useSession} from 'next-auth/react';

function Gate({children}: { children: React.ReactNode }) {
    const {data: session, status} = useSession();
    if (status === 'loading') return <div className="login"><h1>Cache Lab</h1><p>Checking your session…</p></div>;
    if (!session || session.expired) return <div className="login">
        <div className="eyebrow">DISTRIBUTED CACHE WORKBENCH</div>
        <h1>Welcome to Cache Lab.</h1>
        <p>{session?.expired ? 'Your access token expired. Sign in again to continue.' : 'Sign in with Keycloak to access your cache workspace.'}</p>
        <button className="primary" onClick={() => void signIn('keycloak')}>Sign in with Keycloak ↗</button>
    </div>;
    if (!session.roles.some(r => ['cache-user', 'cache-admin'].includes(r))) return <div className="login"><h1>Access
        required</h1><p>Your account needs the cache-user or cache-admin role.</p>
        <button onClick={() => void signOut()}>Sign out</button>
    </div>;
    return <>
        <div className="account">
            <span>{session.user?.name || session.user?.email} · {session.roles.includes('cache-admin') ? 'Admin' : 'User'}</span>
            <button className="subtle" onClick={() => void signOut()}>Sign out</button>
        </div>
        {children}</>;
}

export default function AuthGate({children}: { children: React.ReactNode }) {
    return <SessionProvider refetchInterval={30} refetchOnWindowFocus><Gate>{children}</Gate></SessionProvider>;
}
