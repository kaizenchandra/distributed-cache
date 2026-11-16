import type {Metadata} from 'next';
import './globals.css';
import AuthGate from '../components/auth-gate';

export const metadata: Metadata = {
    title: 'Cache Lab · Distributed Cache',
    description: 'A local workbench for testing distributed cache operations.'
};
export default function RootLayout({children}: Readonly<{ children: React.ReactNode }>) {
    return <html lang="en">
    <body><AuthGate>{children}</AuthGate></body>
    </html>;
}
