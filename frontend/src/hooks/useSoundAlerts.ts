/**
 * useSoundAlerts.ts — Audio notifications using Web Audio API
 *
 * Generates short synthesized tones (no external audio files needed).
 * Persists enabled/disabled state in localStorage.
 */

import { useCallback, useState, useRef } from 'react';

const STORAGE_KEY = 'qs:sound-enabled';

function loadEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'false';
  } catch { return true; }
}

/** Generate a short tone using Web Audio API */
function playTone(frequency: number, duration: number, type: OscillatorType = 'sine', volume = 0.15) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = type;
    osc.frequency.value = frequency;
    gain.gain.value = volume;
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);

    setTimeout(() => ctx.close(), (duration + 0.5) * 1000);
  } catch {
    // Audio not available
  }
}

export function useSoundAlerts() {
  const [enabled, setEnabled] = useState(loadEnabled);
  const lastPlayRef = useRef(0);

  const toggle = useCallback(() => {
    setEnabled(prev => {
      const next = !prev;
      localStorage.setItem(STORAGE_KEY, String(next));
      // Play a test tone when enabling
      if (next) playTone(880, 0.15, 'sine', 0.1);
      return next;
    });
  }, []);

  /** Debounced play — prevents rapid-fire sounds */
  const play = useCallback((fn: () => void) => {
    if (!enabled) return;
    const now = Date.now();
    if (now - lastPlayRef.current < 2000) return; // Min 2s between sounds
    lastPlayRef.current = now;
    fn();
  }, [enabled]);

  /** Ascending two-tone chime — for positive events (signal, alert above) */
  const chimeUp = useCallback(() => {
    play(() => {
      playTone(660, 0.12, 'sine', 0.12);
      setTimeout(() => playTone(880, 0.15, 'sine', 0.12), 130);
    });
  }, [play]);

  /** Descending tone — for warnings (alert below, halt) */
  const chimeDown = useCallback(() => {
    play(() => {
      playTone(880, 0.12, 'sine', 0.12);
      setTimeout(() => playTone(660, 0.15, 'sine', 0.12), 130);
    });
  }, [play]);

  /** Single short beep — for neutral events */
  const beep = useCallback(() => {
    play(() => playTone(740, 0.1, 'sine', 0.1));
  }, [play]);

  return { enabled, toggle, chimeUp, chimeDown, beep };
}
