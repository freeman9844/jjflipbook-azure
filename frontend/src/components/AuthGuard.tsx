"use client";

import {
    useCallback,
    createContext,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";
import { usePathname } from "next/navigation";

interface SessionResponse {
    authenticated: boolean;
    username: string;
    expiresAt: number;
}

interface AuthContextValue {
    logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const FALLBACK_SESSION_TTL_SECONDS = 8 * 60 * 60;

const styles: Record<string, React.CSSProperties> = {
    loginContainer: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', width: '100vw', backgroundColor: '#f4f6f8' },
    loginForm: { backgroundColor: 'white', padding: '40px', borderRadius: '16px', boxShadow: '0 10px 40px rgba(0,0,0,0.06)', width: '340px', display: 'flex', flexDirection: 'column', gap: '12px', boxSizing: 'border-box' },
    loginInput: { padding: '12px 16px', borderRadius: '8px', border: '1px solid #dadce0', fontSize: '14px', outline: 'none', transition: 'border-color 0.2s', width: '100%', boxSizing: 'border-box' },
    loginBtn: { padding: '12px', backgroundColor: '#1a73e8', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: 600, cursor: 'pointer', transition: 'background-color 0.2s', marginTop: '8px', width: '100%' }
};

export function useAuth(): AuthContextValue {
    const value = useContext(AuthContext);
    if (!value) {
        throw new Error('useAuth must be used within AuthGuard');
    }
    return value;
}

export default function AuthGuard({ children }: { children: React.ReactNode }) {
    const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);
    const [sessionExpiresAt, setSessionExpiresAt] = useState<number | null>(null);
    const [loginId, setLoginId] = useState("");
    const [password, setPassword] = useState("");
    const [loginError, setLoginError] = useState("");
    const pathname = usePathname();
    const isPublicRoute = pathname?.startsWith("/view/") || false;
    const authValue = useMemo<AuthContextValue>(() => ({
        logout: () => {
            setSessionExpiresAt(null);
            setIsLoggedIn(false);
        },
    }), []);

    const applySession = useCallback((session: SessionResponse) => {
        setSessionExpiresAt(session.expiresAt);
        setIsLoggedIn(true);
    }, []);

    const validateSession = useCallback(async (failClosed: boolean) => {
        try {
            const res = await fetch('/api/backend/session', {
                cache: 'no-store',
            });

            if (!res.ok) {
                if (failClosed) {
                    setSessionExpiresAt(null);
                    setIsLoggedIn(false);
                }
                return;
            }

            const data = await res.json() as SessionResponse;
            if (!data.authenticated) {
                if (failClosed) {
                    setSessionExpiresAt(null);
                    setIsLoggedIn(false);
                }
                return;
            }

            applySession(data);
        } catch {
            if (failClosed) {
                setSessionExpiresAt(null);
                setIsLoggedIn(false);
            }
        }
    }, [applySession]);

    useEffect(() => {
        if (isPublicRoute) {
            return;
        }

        void validateSession(true);
    }, [isPublicRoute, validateSession]);

    useEffect(() => {
        if (!sessionExpiresAt) {
            return;
        }

        const delay = sessionExpiresAt * 1000 - Date.now();
        if (delay <= 0) {
            setSessionExpiresAt(null);
            setIsLoggedIn(false);
            return;
        }

        const logoutTimer = setTimeout(() => {
            setSessionExpiresAt(null);
            setIsLoggedIn(false);
        }, delay);

        return () => clearTimeout(logoutTimer);
    }, [sessionExpiresAt]);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const res = await fetch(`/api/backend/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: loginId, password })
            });

            if (res.ok) {
                setSessionExpiresAt(
                    Math.floor(Date.now() / 1000) + FALLBACK_SESSION_TTL_SECONDS,
                );
                setIsLoggedIn(true);
                setLoginError("");
                void validateSession(false);
            } else {
                setSessionExpiresAt(null);
                setLoginError("❌ ID 또는 Password가 잘못되었습니다.");
            }
        } catch (err) {
            setSessionExpiresAt(null);
            setLoginError("❌ 서버와 통신할 수 없습니다.");
        }
    };

    if (isPublicRoute) {
        return (
            <AuthContext.Provider value={authValue}>
                {children}
            </AuthContext.Provider>
        );
    }

    if (isLoggedIn === null) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', width: '100vw', backgroundColor: '#f4f6f8', color: '#5f6368', fontSize: '15px' }}>
                인증 확인 중...
            </div>
        );
    }

    if (!isLoggedIn && !isPublicRoute) {
        return (
            <div style={styles.loginContainer}>
                <form onSubmit={handleLogin} style={styles.loginForm}>
                    <h2 style={{ marginBottom: '4px', textAlign: 'center', color: '#1a1a1a', fontWeight: 'bold' }}>JJFlipBook 로그인</h2>
                    <p style={{ margin: '0 0 20px 0', textAlign: 'center', fontSize: '13px', color: '#5f6368' }}>관리자 계정으로 로그인해 주세요.</p>
                    {loginError && <div style={{ color: '#e11d48', fontSize: '13px', marginBottom: '12px', textAlign: 'center', backgroundColor: '#fef2f2', padding: '8px', borderRadius: '6px' }}>{loginError}</div>}
                    <input type="text" placeholder="아이디" value={loginId} onChange={(e) => setLoginId(e.target.value)} style={styles.loginInput} required />
                    <input type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} style={styles.loginInput} required />
                    <button type="submit" style={styles.loginBtn}>로그인</button>
                </form>
            </div>
        );
    }

    return (
        <AuthContext.Provider value={authValue}>
            {children}
        </AuthContext.Provider>
    );
}
