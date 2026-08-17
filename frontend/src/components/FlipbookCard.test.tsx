import { render, screen } from '@testing-library/react';

import FlipbookCard, { type Flipbook } from './FlipbookCard';

const baseBook: Flipbook = {
  id: 'book-1',
  uuid_key: 'book-1',
  title: 'Sample book',
  page_count: 10,
  image_urls: ['https://storage.example/page-1.webp'],
  created_at: '2026-08-17T00:00:00Z',
};

test('renders responsive pre-generated covers without the Next image optimizer', () => {
  render(
    <FlipbookCard
      book={{
        ...baseBook,
        cover_urls: [
          'https://storage.example/cover-384.webp',
          'https://storage.example/cover-640.webp',
        ],
      }}
      isMobile={false}
      onDelete={jest.fn()}
      onOpen={jest.fn()}
    />,
  );

  const image = screen.getByRole('img', { name: 'Sample book' });
  expect(image).toHaveAttribute(
    'srcset',
    'https://storage.example/cover-384.webp 384w, https://storage.example/cover-640.webp 640w',
  );
  expect(image).toHaveAttribute('src', 'https://storage.example/cover-640.webp');
  expect(image).toHaveAttribute(
    'sizes',
    '(min-width: 768px) and (max-width: 771px) 430px, 260px',
  );
  expect(image.getAttribute('src')).not.toContain('/_next/image');
});

test('falls back to the first page for books created before cover thumbnails', () => {
  render(
    <FlipbookCard
      book={baseBook}
      isMobile={false}
      onDelete={jest.fn()}
      onOpen={jest.fn()}
    />,
  );

  const image = screen.getByRole('img', { name: 'Sample book' });
  expect(image).toHaveAttribute('src', 'https://storage.example/page-1.webp');
  expect(image).not.toHaveAttribute('srcset');
});
