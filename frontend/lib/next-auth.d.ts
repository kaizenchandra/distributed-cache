import 'next-auth';
import 'next-auth/jwt';
declare module 'next-auth' { interface Session { roles: string[]; expired: boolean } }
declare module 'next-auth/jwt' { interface JWT { accessToken?: string; accessExpires?: number; roles?: string[] } }
