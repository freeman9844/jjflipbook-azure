import {
  createHmac,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';

export const SESSION_TTL_SECONDS = 8 * 60 * 60;

export interface SessionPayload {
  username: string;
  iat: number;
  exp: number;
  nonce: string;
}

const LEGACY_DEFAULT = 'simple-mvp-session-secret-123';

function sessionSecret(): string {
  const value = process.env.SESSION_SECRET;
  if (
    process.env.NODE_ENV === 'production'
    && (!value || value === LEGACY_DEFAULT || value.length < 32)
  ) {
    throw new Error('SESSION_SECRET must be configured with at least 32 characters');
  }
  return value || LEGACY_DEFAULT;
}

function encode(value: string | Buffer): string {
  return Buffer.from(value).toString('base64url');
}

function signature(encodedPayload: string): Buffer {
  return createHmac('sha256', sessionSecret()).update(encodedPayload).digest();
}

export function createSessionToken(
  username: string,
  nowSeconds = Math.floor(Date.now() / 1000),
  nonce = randomBytes(16).toString('base64url'),
): string {
  const payload: SessionPayload = {
    username,
    iat: nowSeconds,
    exp: nowSeconds + SESSION_TTL_SECONDS,
    nonce,
  };
  const encodedPayload = encode(JSON.stringify(payload));
  return `${encodedPayload}.${encode(signature(encodedPayload))}`;
}

export function verifySessionToken(
  token: string | undefined,
  nowSeconds = Math.floor(Date.now() / 1000),
): SessionPayload | null {
  if (!token) {
    return null;
  }

  const parts = token.split('.');
  if (parts.length !== 2) {
    return null;
  }

  const [encodedPayload, encodedSignature] = parts;

  try {
    const expected = signature(encodedPayload);
    const actual = Buffer.from(encodedSignature, 'base64url');
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      return null;
    }

    const payload = JSON.parse(
      Buffer.from(encodedPayload, 'base64url').toString('utf8'),
    ) as SessionPayload;

    if (
      payload.username.length === 0
      || !Number.isInteger(payload.iat)
      || !Number.isInteger(payload.exp)
      || payload.exp <= nowSeconds
      || payload.exp - payload.iat !== SESSION_TTL_SECONDS
      || payload.nonce.length === 0
    ) {
      return null;
    }

    return payload;
  } catch {
    return null;
  }
}
