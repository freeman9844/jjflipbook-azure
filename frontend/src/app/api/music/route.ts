import { NextResponse } from 'next/server';

interface GcsObject {
    name: string;
}

interface GcsListResponse {
    items?: GcsObject[];
}

export async function GET() {
    const bucketName = process.env.GCS_BUCKET_NAME || 'jjflipbook-gcs-001';
    const bucketUrl = `https://storage.googleapis.com/storage/v1/b/${bucketName}/o?prefix=bgm/`;

    try {
        const res = await fetch(bucketUrl, { next: { revalidate: 3600 } });
        if (!res.ok) {
            return NextResponse.json({ files: [] });
        }

        const data: GcsListResponse = await res.json();
        if (!data.items) {
            return NextResponse.json({ files: [] });
        }

        const files = data.items
            .filter((item) => item.name.endsWith('.mp3'))
            .map((item) => `https://storage.googleapis.com/${bucketName}/${item.name}`);

        return NextResponse.json({ files });
    } catch {
        return NextResponse.json({ files: [] }, { status: 500 });
    }
}
