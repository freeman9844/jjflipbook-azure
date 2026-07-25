/** @jest-environment node */
import { GET } from './route';

describe('GET /api/music (Azure Blob List)', () => {
    const XML = `<?xml version="1.0" encoding="utf-8"?>
<EnumerationResults><Blobs>
<Blob><Name>bgm/song1.mp3</Name></Blob>
<Blob><Name>bgm/notes.txt</Name></Blob>
<Blob><Name>bgm/song2.mp3</Name></Blob>
</Blobs></EnumerationResults>`;

    beforeEach(() => {
        process.env.STORAGE_ACCOUNT_NAME = 'teststorage';
        process.env.BLOB_CONTAINER_NAME = 'flipbook-assets';
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            text: () => Promise.resolve(XML),
        }) as jest.Mock;
    });

    it('returns only .mp3 files as public blob URLs', async () => {
        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual([
            'https://teststorage.blob.core.windows.net/flipbook-assets/bgm/song1.mp3',
            'https://teststorage.blob.core.windows.net/flipbook-assets/bgm/song2.mp3',
        ]);
        const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
        expect(calledUrl).toContain('restype=container&comp=list&prefix=bgm/');
    });

    it('returns empty list when storage account is not configured', async () => {
        delete process.env.STORAGE_ACCOUNT_NAME;
        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual([]);
    });
});
