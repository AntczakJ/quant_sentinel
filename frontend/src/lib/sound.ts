/**
 * Lightweight WebAudio synth — zero asset files.
 *
 * All tones are short sine/triangle pulses with envelope shaping. Volume is
 * intentionally tiny (max 0.06) to read as ambient feedback, not alerts.
 *
 * Usage:
 *   import { playWin, playLoss, playClick, isSoundEnabled, setSoundEnabled } from '@/lib/sound'
 *
 *   if (isSoundEnabled()) playClick()
 *
 * Persistence: localStorage key `qs.sound.enabled`, default `false`.
 */

const STORAGE_KEY = 'qs.sound.enabled'

let ctx: AudioContext | null = null

function getCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (ctx) return ctx
  const Ctor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return null
  ctx = new Ctor()
  return ctx
}

export function isSoundEnabled(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(STORAGE_KEY) === '1'
}

export function setSoundEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0')
}

/**
 * Play a tone with explicit envelope. Frequency in Hz, duration in seconds.
 * Volume is clamped to [0, 0.08] for safety. Always non-blocking.
 */
function playTone({
  freq,
  duration = 0.08,
  type = 'sine',
  volume = 0.04,
  attack = 0.005,
  release = 0.05,
}: {
  freq: number
  duration?: number
  type?: OscillatorType
  volume?: number
  attack?: number
  release?: number
}): void {
  if (!isSoundEnabled()) return
  const c = getCtx()
  if (!c) return
  // Resume audio context on first user gesture (browser autoplay policy)
  if (c.state === 'suspended') c.resume().catch(() => {})

  const osc = c.createOscillator()
  const gain = c.createGain()
  osc.type = type
  osc.frequency.value = freq

  const now = c.currentTime
  const v = Math.min(0.08, Math.max(0, volume))
  gain.gain.setValueAtTime(0, now)
  gain.gain.linearRampToValueAtTime(v, now + attack)
  gain.gain.setValueAtTime(v, now + attack + duration)
  gain.gain.linearRampToValueAtTime(0, now + attack + duration + release)

  osc.connect(gain)
  gain.connect(c.destination)
  osc.start(now)
  osc.stop(now + attack + duration + release + 0.02)
}

/** Two-tone "win" — perfect fifth, bright. */
export function playWin(): void {
  playTone({ freq: 880, duration: 0.06, type: 'triangle', volume: 0.05 })
  setTimeout(() => playTone({ freq: 1320, duration: 0.08, type: 'triangle', volume: 0.045 }), 80)
}

/** Descending minor third "loss" — soft, not aggressive. */
export function playLoss(): void {
  playTone({ freq: 440, duration: 0.08, type: 'sine', volume: 0.045 })
  setTimeout(() => playTone({ freq: 370, duration: 0.10, type: 'sine', volume: 0.04 }), 80)
}

/** Short blip — Cmd+K confirmation. */
export function playClick(): void {
  playTone({ freq: 1180, duration: 0.025, type: 'sine', volume: 0.025, attack: 0.002, release: 0.02 })
}

/** Tick flash — even subtler than click. Used on price-tick highlights. */
export function playTick(): void {
  playTone({ freq: 720, duration: 0.018, type: 'triangle', volume: 0.018, attack: 0.002, release: 0.015 })
}
