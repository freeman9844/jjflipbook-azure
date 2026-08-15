import React from 'react';
import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import AuthGuard from './AuthGuard';

jest.mock('next/navigation', () => ({
  usePathname: () => '/',
}));

describe('AuthGuard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders protected content after server session validation', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        username: 'admin',
        expiresAt: Math.floor(Date.now() / 1000) + 3600,
      }),
    }) as jest.Mock;

    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    expect(await screen.findByText('Protected Content')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith('/api/backend/session', {
      cache: 'no-store',
    });
  });

  it('shows login when session validation returns 401', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 }) as jest.Mock;
    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    expect(await screen.findByText('JJFlipBook 로그인')).toBeInTheDocument();
  });

  it('sets authenticated state after successful login', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({ ok: true });

    render(<AuthGuard><div>Protected Content</div></AuthGuard>);
    await screen.findByText('JJFlipBook 로그인');
    fireEvent.change(screen.getByPlaceholderText('아이디'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByPlaceholderText('비밀번호'), {
      target: { value: 'password' },
    });
    fireEvent.click(screen.getByText('로그인'));

    expect(await screen.findByText('Protected Content')).toBeInTheDocument();
  });
});
