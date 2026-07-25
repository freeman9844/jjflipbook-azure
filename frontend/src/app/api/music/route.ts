import { NextResponse } from 'next/server';

export async function GET() {
    const accountName = process.env.STORAGE_ACCOUNT_NAME || '';
    const containerName = process.env.BLOB_CONTAINER_NAME || 'flipbook-assets';

    if (!accountName) {
        return NextResponse.json({ files: [] });
    }

    const baseUrl = `https://${accountName}.blob.core.windows.net/${containerName}`;
    const listUrl = `${baseUrl}?restype=container&comp=list&prefix=bgm/`;

    try {
        const res = await fetch(listUrl, { next: { revalidate: 3600 } });
        if (!res.ok) {
            return NextResponse.json({ files: [] });
        }

        const xml = await res.text();
        const names = [...xml.matchAll(/<Name>([^<]+)<\/Name>/g)].map((m) => m[1]);

        const files = names
            .filter((name) => name.endsWith('.mp3'))
            .map((name) => `${baseUrl}/${name}`);

        return NextResponse.json({ files });
    } catch {
        return NextResponse.json({ files: [] }, { status: 500 });
    }
}
