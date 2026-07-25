import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const SESSION_TOKEN = process.env.SESSION_SECRET || "simple-mvp-session-secret-123";

function isAuthenticated(request: NextRequest) {
    const token = request.cookies.get('auth_token')?.value;
    return token === SESSION_TOKEN;
}

// GET Proxy
export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> }
) {
    const resolvedParams = await params;
    const pathStr = resolvedParams.path.join('/');

    // /folders, /flipbooks (대시보드 목록)는 인증 필요
    // /flipbook/:uuid, /flipbook/:uuid/overlays는 공개 접근 허용 (뷰어 공유용)
    if (pathStr === 'folders' || pathStr === 'flipbooks') {
        if (!isAuthenticated(request)) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }
    }

    const searchParams = request.nextUrl.search;
    const url = `${BACKEND_URL}/${pathStr}${searchParams}`;

    try {
        const res = await fetch(url, { cache: 'no-store' });
        const responseContentType = res.headers.get('content-type') || '';
        const data = responseContentType.includes('application/json')
            ? await res.json()
            : { message: await res.text() };
        return NextResponse.json(data, { status: res.status });
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Internal proxy error';
        return NextResponse.json({ error: message }, { status: 500 });
    }
}

// POST Proxy
export async function POST(
    request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> }
) {
    const resolvedParams = await params;
    const pathStr = resolvedParams.path.join('/');
    const searchParams = request.nextUrl.search;
    const url = `${BACKEND_URL}/${pathStr}${searchParams}`;

    // 로그아웃은 프론트엔드에서만 처리 (쿠키 삭제)
    if (pathStr === 'logout') {
        const resObj = NextResponse.json({ status: 'ok', message: 'Logged out' });
        resObj.cookies.delete('auth_token');
        return resObj;
    }

    // 로그인 외 모든 POST는 인증 필요
    if (pathStr !== 'login' && !isAuthenticated(request)) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    try {
        const contentType = request.headers.get('content-type') || 'application/json';
        const apiKey = process.env.INTERNAL_API_KEY || 'secret_dev_key';

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 600000); // 10분 타임아웃

        const res = await fetch(url, {
            method: 'POST',
            body: request.body,
            headers: {
                'Content-Type': contentType,
                'X-API-Key': apiKey,
            },
            signal: controller.signal,
            // Node.js fetch에서 스트리밍 body를 지원하기 위한 설정
            ...(({ duplex: 'half' }) as Record<string, unknown>),
        } as RequestInit);

        clearTimeout(timeoutId);

        const responseContentType = res.headers.get('content-type') || '';
        const data = responseContentType.includes('application/json')
            ? await res.json()
            : { message: await res.text() };

        const resObj = NextResponse.json(data, { status: res.status });

        // 로그인 성공 시 HttpOnly 쿠키 발급
        if (pathStr === 'login' && res.ok && data.authenticated) {
            resObj.cookies.set('auth_token', SESSION_TOKEN, {
                httpOnly: true,
                secure: process.env.NODE_ENV === 'production',
                sameSite: 'lax',
                path: '/',
            });
        }

        return resObj;
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Internal proxy error';
        return NextResponse.json({ error: message }, { status: 500 });
    }
}

// DELETE Proxy
export async function DELETE(
    request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> }
) {
    if (!isAuthenticated(request)) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const resolvedParams = await params;
    const pathStr = resolvedParams.path.join('/');
    const searchParams = request.nextUrl.search;
    const url = `${BACKEND_URL}/${pathStr}${searchParams}`;

    try {
        const res = await fetch(url, {
            method: 'DELETE',
            headers: { 'X-API-Key': process.env.INTERNAL_API_KEY || 'secret_dev_key' },
        });
        const responseContentType = res.headers.get('content-type') || '';
        const data = responseContentType.includes('application/json')
            ? await res.json()
            : { message: await res.text() };
        return NextResponse.json(data, { status: res.status });
    } catch (error) {
        const message = error instanceof Error ? error.message : 'Internal proxy error';
        return NextResponse.json({ error: message }, { status: 500 });
    }
}
