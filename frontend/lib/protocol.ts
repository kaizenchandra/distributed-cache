export const operations = ['GET', 'SET', 'DELETE', 'EXISTS', 'TTL', 'EXPIRE', 'CAS'] as const;

export function encode(text: string) {
    const bytes = new TextEncoder().encode(text);
    return btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
}

export function makeOperation(operation: string, key: string, value: string, ttl: number, version?: number) {
    const encodedKey = encode(key).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
    if (!key || encodedKey.length > 512) throw new Error('Key must contain 1–512 Base64url characters after UTF-8 encoding.');
    if (!operations.includes(operation as typeof operations[number])) throw new Error('Unknown operation.');
    if (!Number.isSafeInteger(ttl) || ttl < -1 || ttl > 31536000000) throw new Error('TTL must be an integer from -1 to 31,536,000,000 ms.');
    if (new TextEncoder().encode(value).length > 65536) throw new Error('Value exceeds 64 KiB.');
    if (operation === 'CAS' && (!Number.isSafeInteger(version) || version! < 0)) throw new Error('CAS requires a nonnegative integer version.');
    return {
        operation,
        key: encodedKey, ...(['SET', 'CAS'].includes(operation) ? {value: encode(value)} : {}),
        ttlMillis: ttl, ...(operation === 'CAS' ? {expectedVersion: version} : {})
    };
}

export function decode(value: string) {
    try {
        return new TextDecoder('utf-8', {fatal: true}).decode(Uint8Array.from(atob(value), c => c.charCodeAt(0)));
    } catch {
        return '[Binary value; see Base64 in raw response]';
    }
}
