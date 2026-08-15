export interface OverlayInput {
  id?: string;
  page: number;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  data_url: string;
}

export interface EditableOverlay extends OverlayInput {
  clientId: string;
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random()}`;
}

export function hydrateOverlays(
  overlays: OverlayInput[],
  createId: () => string = newClientId,
): EditableOverlay[] {
  return overlays.map((overlay) => ({
    ...overlay,
    clientId: overlay.id || createId(),
  }));
}

export function updateOverlay(
  overlays: EditableOverlay[],
  clientId: string,
  patch: Partial<OverlayInput>,
): EditableOverlay[] {
  return overlays.map((overlay) =>
    overlay.clientId === clientId ? { ...overlay, ...patch } : overlay,
  );
}

export function removeOverlay(
  overlays: EditableOverlay[],
  clientId: string,
): EditableOverlay[] {
  return overlays.filter((overlay) => overlay.clientId !== clientId);
}

export function serializeOverlays(overlays: EditableOverlay[]): OverlayInput[] {
  return overlays.map(({ clientId: _clientId, ...overlay }) => overlay);
}
