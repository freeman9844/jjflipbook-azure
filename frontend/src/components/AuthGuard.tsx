"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

const styles: Record<string, React.CSSProperties> = {
    loginContainer: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', width: '100vw', backgroundColor: '#f4f6f8' },
    loginForm: { backgroundColor: 'white', padding: '40px', borderRadius: '16px', boxShadow: '0 10px 40px rgba(0,0,0,0.06)', width: '340px', display: 'flex', flexDirection: 'column', gap: '12px', boxSizing: 'border-box' },
    loginInput: { padding: '12px 16px', borderRadius: '8px', border: '1px solid #dadce0', fontSize: '14px', outline: 'none', transition: 'border-color 0.2s', width: '100%', boxSizing: 'border-box' },
    loginBtn: { padding: '12px', backgroundColor: '#1a73e8', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: 600, cursor: 'pointer', transition: 'background-color 0.2s', marginTop: '8px', width: '100%' }
};

export default function AuthGuard({ children }: { children: React.ReactNode }) {
    const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);
    const [loginId, setLoginId] = useState("");
    const [password, setPassword] = useState("");
    const [loginError, setLoginError] = useState("");
    const pathname = usePathname();

    useEffect(() => {
        if (typeof window !== "undefined") {
            const auth = localStorage.getItem("isAuthenticated");
            setIsLoggedIn(auth === "true");
        }
    }, []);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const res = await fetch(`/api/backend/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: loginId, password })
            });

            if (res.ok) {
                localStorage.setItem("isAuthenticated", "true");
                setIsLoggedIn(true);
                setLoginError("");
            } else {
                setLoginError("❌ ID 또는 Password가 잘못되었습니다.");
            }
        } catch (err) {
            setLoginError("❌ 서버와 통신할 수 없습니다.");
        }
    };

    if (isLoggedIn === null) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', width: '100vw', backgroundColor: '#f4f6f8', color: '#5f6368', fontSize: '15px' }}>
                인증 확인 중...
            </div>
        );
    }

    const isPublicRoute = pathname?.startsWith("/view/") || false;

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

    return <>{children}</>;
}

