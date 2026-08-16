/** @jest-environment node */
import { NextRequest } from 'next/server';
import { GET, POST } from './route';

describe('/api/backend proxy sessions', () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = 'test-session-secret-at-least-32-bytes';
    process.env.INTERNAL_API_KEY = 'test-internal-api-key';
    process.env.NEXT_PUBLIC_BACKEND_URL = 'https://backend.internal';
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
    delete process.env.SESSION_SECRET;
    delete process.env.INTERNAL_API_KEY;
    delete process.env.NEXT_PUBLIC_BACKEND_URL;
  });

  it('issues an eight-hour HttpOnly cookie after login', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({
        authenticated: true,
        username: 'admin',
        status: 'ok',
      }),
    }) as jest.Mock;

    const request = new NextRequest('https://frontend/api/backend/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'password' }),
    });
    const response = await POST(request, {
      params: Promise.resolve({ path: ['login'] }),
    });

    expect(response.status).toBe(200);
    const cookie = response.headers.get('set-cookie') || '';
    expect(cookie).toContain('auth_token=');
    expect(cookie.toLowerCase()).toContain('httponly');
    expect(cookie).toContain('Max-Age=28800');
    expect(cookie).toContain('Expires=');
  });

  it('returns the validated session without forwarding to FastAPI', async () => {
    const loginRequest = new NextRequest('https://frontend/api/backend/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'password' }),
    });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ authenticated: true, username: 'admin' }),
    }) as jest.Mock;
    const loginResponse = await POST(loginRequest, {
      params: Promise.resolve({ path: ['login'] }),
    });
    const cookie = (loginResponse.headers.get('set-cookie') || '').split(';')[0];
    (global.fetch as jest.Mock).mockClear();

    const response = await GET(
      new NextRequest('https://frontend/api/backend/session', {
        headers: { cookie },
      }),
      { params: Promise.resolve({ path: ['session'] }) },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({
      authenticated: true,
      username: 'admin',
    }));
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('returns 504 when a backend GET exceeds thirty seconds', async () => {
    jest.useFakeTimers();
    global.fetch = jest.fn((_url, init) => new Promise((_resolve, reject) => {
      const signal = (init as RequestInit).signal;
      signal?.addEventListener('abort', () => {
        reject(new DOMException('Aborted', 'AbortError'));
      });
    })) as jest.Mock;

    let settled = false;
    const responsePromise = GET(
      new NextRequest('https://frontend/api/backend/flipbook/book-1'),
      { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
    );
    void responsePromise.finally(() => {
      settled = true;
    });
    await jest.advanceTimersByTimeAsync(30000);
    expect(settled).toBe(true);
    if (!settled) {
      return;
    }
    const response = await responsePromise;

    expect(response.status).toBe(504);
    expect(await response.json()).toEqual({
      error: 'Backend request timed out',
    });
    jest.useRealTimers();
  });

  it('returns 502 when a backend GET connection fails', async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError('fetch failed'));

    const response = await GET(
      new NextRequest('https://frontend/api/backend/flipbook/book-1'),
      { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      error: 'Backend connection failed',
    });
  });

  it('preserves completed backend GET JSON status and body', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      headers: new Headers({ 'content-type': 'application/json' }),
      status: 418,
      json: async () => ({
        message: 'teapot',
        detail: 'brew required',
      }),
    }) as jest.Mock;

    const response = await GET(
      new NextRequest('https://frontend/api/backend/flipbook/book-1'),
      { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
    );

    expect(response.status).toBe(418);
    expect(await response.json()).toEqual({
      message: 'teapot',
      detail: 'brew required',
    });
  });

  it('preserves completed backend GET text status and wraps the body', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      headers: new Headers({ 'content-type': 'text/plain' }),
      status: 503,
      text: async () => 'service unavailable',
    }) as jest.Mock;

    const response = await GET(
      new NextRequest('https://frontend/api/backend/flipbook/book-1'),
      { params: Promise.resolve({ path: ['flipbook', 'book-1'] }) },
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      message: 'service unavailable',
    });
  });
});
