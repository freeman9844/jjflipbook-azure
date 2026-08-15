import {
  hydrateOverlays,
  removeOverlay,
  serializeOverlays,
  updateOverlay,
} from './overlays';

const source = [
  {
    id: 'page-1-overlay',
    page: 1,
    type: 'link',
    x: 1,
    y: 2,
    width: 10,
    height: 20,
    data_url: 'https://one.example',
  },
  {
    id: 'page-2-overlay',
    page: 2,
    type: 'link',
    x: 3,
    y: 4,
    width: 10,
    height: 20,
    data_url: 'https://two.example',
  },
];

describe('overlay editor helpers', () => {
  it('updates the selected page-two overlay without changing page one', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    const updated = updateOverlay(overlays, 'page-2-overlay', {
      data_url: 'https://updated.example',
    });

    expect(updated[0].data_url).toBe('https://one.example');
    expect(updated[1].data_url).toBe('https://updated.example');
  });

  it('removes only the selected overlay', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    const remaining = removeOverlay(overlays, 'page-2-overlay');
    expect(remaining.map((item) => item.id)).toEqual(['page-1-overlay']);
  });

  it('does not send clientId to the backend', () => {
    const overlays = hydrateOverlays(source, () => 'generated');
    expect(serializeOverlays(overlays)[0]).not.toHaveProperty('clientId');
  });
});
