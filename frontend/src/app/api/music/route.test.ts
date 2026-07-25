/** @jest-environment node */
import { GET } from './route';

describe('GET /api/music', () => {
    const BACKEND_URL = 'https://backend.example.com';

    beforeEach(() => {
        process.env.NEXT_PUBLIC_BACKEND_URL = BACKEND_URL;
    });

    afterEach(() => {
        delete process.env.NEXT_PUBLIC_BACKEND_URL;
        jest.resetAllMocks();
    });

    it('passes through files from the backend music/list endpoint', async () => {
        const mockFiles = [
            'https://st.blob.core.windows.net/flipbook-assets/bgm/song1.mp3?sv=...',
            'https://st.blob.core.windows.net/flipbook-assets/bgm/song2.mp3?sv=...',
        ];
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ files: mockFiles }),
        }) as jest.Mock;

        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual(mockFiles);

        const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
        expect(calledUrl).toBe(`${BACKEND_URL}/music/list`);
    });

    it('returns empty list when NEXT_PUBLIC_BACKEND_URL is not set', async () => {
        delete process.env.NEXT_PUBLIC_BACKEND_URL;
        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual([]);
    });

    it('returns empty list when backend fetch fails', async () => {
        global.fetch = jest.fn().mockRejectedValue(new Error('network error')) as jest.Mock;
        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual([]);
    });

    it('returns empty list when backend returns non-ok status', async () => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
        }) as jest.Mock;
        const res = await GET();
        const body = await res.json();
        expect(body.files).toEqual([]);
    });
});

