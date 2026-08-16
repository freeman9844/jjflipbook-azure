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

        expect(global.fetch).toHaveBeenCalledWith(
            `${BACKEND_URL}/music/list`,
            { cache: 'no-store' },
        );
    });

    it('returns 503 when backend configuration is missing', async () => {
        delete process.env.NEXT_PUBLIC_BACKEND_URL;
        const response = await GET();
        expect(response.status).toBe(503);
    });

    it('returns 502 when backend fetch fails', async () => {
        global.fetch = jest.fn().mockRejectedValue(new Error('network error')) as jest.Mock;
        const response = await GET();
        expect(response.status).toBe(502);
    });

    it('preserves backend failure status', async () => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: false,
            status: 503,
        }) as jest.Mock;
        const response = await GET();
        expect(response.status).toBe(503);
    });
});
