import {
  SESSION_TTL_SECONDS,
  createSessionToken,
  verifySessionToken,
} from './session';

describe('signed administrator sessions', () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = 'test-session-secret-at-least-32-bytes';
  });

  afterEach(() => {
    delete process.env.SESSION_SECRET;
  });

  it('accepts a valid token and fixes expiry at eight hours', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    const payload = verifySessionToken(token, 1_001);

    expect(payload).toEqual({
      username: 'admin',
      iat: 1_000,
      exp: 1_000 + SESSION_TTL_SECONDS,
      nonce: 'fixed-nonce',
    });
  });

  it('rejects an expired token', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    expect(verifySessionToken(token, 1_000 + SESSION_TTL_SECONDS)).toBeNull();
  });

  it('rejects a tampered payload', () => {
    const token = createSessionToken('admin', 1_000, 'fixed-nonce');
    const [payload, signature] = token.split('.');
    const tampered = `${payload.slice(0, -1)}A.${signature}`;
    expect(verifySessionToken(tampered, 1_001)).toBeNull();
  });

  it('rejects malformed tokens', () => {
    expect(verifySessionToken('not-a-session', 1_000)).toBeNull();
  });

  it('fails closed without a production session secret', () => {
    delete process.env.SESSION_SECRET;
    const originalNodeEnv = process.env.NODE_ENV;
    Object.defineProperty(process.env, 'NODE_ENV', {
      value: 'production',
      configurable: true,
    });

    expect(() => createSessionToken('admin', 1_000, 'nonce')).toThrow(
      'SESSION_SECRET must be configured',
    );

    Object.defineProperty(process.env, 'NODE_ENV', {
      value: originalNodeEnv,
      configurable: true,
    });
  });
});
