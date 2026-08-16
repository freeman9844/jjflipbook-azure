import { NextResponse } from 'next/server';

export async function GET() {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

    if (!backendUrl) {
        return NextResponse.json(
            { error: 'Music backend is not configured' },
            { status: 503 },
        );
    }

    try {
        const res = await fetch(`${backendUrl}/music/list`, { cache: 'no-store' });
        if (!res.ok) {
            return NextResponse.json(
                { error: 'Music service unavailable' },
                { status: res.status },
            );
        }
        const data = await res.json();
        return NextResponse.json(data);
    } catch {
        return NextResponse.json(
            { error: 'Music backend connection failed' },
            { status: 502 },
        );
    }
}
