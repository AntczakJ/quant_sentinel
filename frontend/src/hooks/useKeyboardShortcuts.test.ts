import { describe, it, expect, vi } from 'vitest';
import { SHORTCUT_LIST } from './useKeyboardShortcuts';

describe('SHORTCUT_LIST', () => {
  it('has all expected shortcuts', () => {
    const keys = SHORTCUT_LIST.map(s => s.key);
    expect(keys).toContain('T');
    expect(keys).toContain('1-4');
    expect(keys).toContain('D');
    expect(keys).toContain('Esc');
    expect(keys).toContain('Space');
    expect(keys).toContain('S');
    expect(keys).toContain('?');
    expect(keys).toContain('Alt+Click');
  });

  it('each shortcut has a description', () => {
    for (const s of SHORTCUT_LIST) {
      expect(s.description).toBeTruthy();
      expect(s.description.length).toBeGreaterThan(5);
    }
  });
});
