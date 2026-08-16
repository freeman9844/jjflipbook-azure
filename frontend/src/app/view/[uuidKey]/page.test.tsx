import React from 'react';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import FlipbookViewer from './page';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('react-pageflip', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

jest.mock('@/components/MusicPlayer', () => ({
  __esModule: true,
  default: () => null,
}));

describe('FlipbookViewer image loading', () => {
  beforeEach(() => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === '/api/backend/session') {
        return { ok: false, status: 401 } as Response;
      }
      if (url.endsWith('/overlays')) {
        return {
          ok: true,
          json: async () => [],
        } as Response;
      }

      return {
        ok: true,
        json: async () => ({
          uuid_key: 'book-id',
          title: 'Sample',
          page_count: 3,
          image_urls: [
            'https://example.test/page-1.jpg',
            'https://example.test/page-2.jpg',
            'https://example.test/page-3.jpg',
          ],
        }),
      } as Response;
    }) as jest.Mock;
  });

  it('prioritizes the first spread and lazily loads later pages', async () => {
    const params = Promise.resolve({ uuidKey: 'book-id' }) as Promise<{
      uuidKey: string;
    }> & {
      status: 'fulfilled';
      value: { uuidKey: string };
    };
    params.status = 'fulfilled';
    params.value = { uuidKey: 'book-id' };

    render(
      <FlipbookViewer params={params} />,
    );

    const firstPage = await screen.findByAltText('Page 1');
    const secondPage = screen.getByAltText('Page 2');
    const thirdPage = screen.getByAltText('Page 3');

    expect(firstPage).toHaveAttribute('loading', 'eager');
    expect(firstPage).toHaveAttribute('fetchpriority', 'high');
    expect(secondPage).toHaveAttribute('loading', 'eager');
    expect(thirdPage).toHaveAttribute('loading', 'lazy');
  });
});
