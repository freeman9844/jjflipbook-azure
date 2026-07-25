import { NextResponse } from 'next/server';

export async function GET() {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

    if (!backendUrl) {
        return NextResponse.json({ files: [] });
    }

    try {
        const res = await fetch(`${backendUrl}/music/list`, { next: { revalidate: 3600 } });
        if (!res.ok) {
            return NextResponse.json({ files: [] });
        }
        const data = await res.json();
        return NextResponse.json(data);
    } catch {
        return NextResponse.json({ files: [] }, { status: 500 });
    }
}

