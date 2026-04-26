/**
 * lib/motion.ts — Shared Motion primitives.
 *
 * Single source of truth for easing curves, durations, and reusable variants
 * across the app. Import these rather than re-declaring ease arrays locally so
 * every transition on the site shares the same "feel" — crucial for the
 * premium impression of cohesion.
 *
 * Typing note: Motion v12 demands tuple types for cubic-bezier arrays, hence
 * the `as const` on every easing literal. Don't remove — TypeScript will fail.
 */

// ── Easing curves ────────────────────────────────────────────────────────

/** Default curve — quick acceleration, long settle. Feels snappy but calm. */
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

/** Symmetric smooth-in-out. Use for toggles and reversible states. */
export const EASE_IN_OUT = [0.65, 0, 0.35, 1] as const;

/** Apple-style deceleration. Slightly more linear at the start, long tail. */
export const EASE_APPLE = [0.25, 0.1, 0.25, 1] as const;

/** Material-ish standard. Used when content appears with momentum. */
export const EASE_STANDARD = [0.4, 0, 0.2, 1] as const;

// ── Durations (seconds) ──────────────────────────────────────────────────

/** Use for tiny visual feedback — button press, chip toggle. */
export const DUR_XS = 0.12;
/** Default micro-interaction duration — hover, tooltip, focus ring. */
export const DUR_SM = 0.18;
/** Standard reveal — cards appearing, page headers. */
export const DUR_MD = 0.32;
/** Long reveal — hero tiles, dramatic entrances. */
export const DUR_LG = 0.5;

// ── Spring presets ───────────────────────────────────────────────────────

/** Snappy spring for layout changes (tab underline, pill indicators). */
export const SPRING_SNAP = { type: 'spring', stiffness: 380, damping: 30 } as const;

/** Soft spring for content motion — less bounce, more authority. */
export const SPRING_SOFT = { type: 'spring', stiffness: 240, damping: 28 } as const;

// ── Variants: stagger containers ────────────────────────────────────────

/**
 * Parent container that staggers its children's reveal.
 *
 *   <motion.div variants={staggerContainer()} initial="hidden" animate="show">
 *     {items.map(item => <motion.div variants={staggerItem}>{item}</motion.div>)}
 *   </motion.div>
 */
export const staggerContainer = (stagger = 0.04, delayChildren = 0) =>
  ({
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { staggerChildren: stagger, delayChildren },
    },
  }) as const;

/** Child variant that rises + fades in. Pairs with staggerContainer. */
export const staggerItem = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: DUR_MD, ease: EASE_OUT },
  },
} as const;

/** Child variant with larger y-offset — use for hero-style content. */
export const staggerItemLarge = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: DUR_LG, ease: EASE_OUT },
  },
} as const;

// ── Variants: single-element reveals ────────────────────────────────────

export const fadeIn = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: DUR_MD, ease: EASE_OUT } },
} as const;

export const fadeInUp = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: DUR_MD, ease: EASE_OUT } },
} as const;

export const scaleIn = {
  hidden: { opacity: 0, scale: 0.96 },
  show: { opacity: 1, scale: 1, transition: { duration: DUR_SM, ease: EASE_OUT } },
} as const;

// ── Page transition ─────────────────────────────────────────────────────

/** Route transition — crossfade with subtle y-shift. Short enough to stay snappy. */
export const pageTransition = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.22, ease: EASE_OUT },
} as const;

// ── Mind-blowing presets (rev. 2026-04-24) ─────────────────────────────

/** Tap-spring — the tactile "press" that defines Apple's HIG. */
export const TAP_SPRING = { type: 'spring', stiffness: 500, damping: 28 } as const;

/** Bouncy spring — overshoot for delight micro-interactions. Use sparingly. */
export const SPRING_BOUNCY = { type: 'spring', stiffness: 320, damping: 18 } as const;

/** Hero entry — large UI elements arriving with momentum. */
export const heroEnter = {
  initial: { opacity: 0, y: 24, scale: 0.96 },
  animate: { opacity: 1, y: 0, scale: 1 },
  transition: { type: 'spring', stiffness: 260, damping: 26 },
} as const;

/** Card lift — subtle elevation on mount. */
export const cardLift = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT },
} as const;

/** Magnetic hover — gentle scale up, snap-back on press. */
export const magneticHover = {
  whileHover: { scale: 1.015 },
  whileTap: { scale: 0.985 },
  transition: TAP_SPRING,
} as const;

/** Number-flip variant — for animated price/stat counter. */
export const numFlip = {
  initial: { opacity: 0, y: '100%' },
  animate: { opacity: 1, y: '0%' },
  exit: { opacity: 0, y: '-100%' },
  transition: { duration: 0.32, ease: EASE_APPLE },
} as const;

/** Glass morphism panel — appears with subtle blur ramp. */
export const glassPanelEnter = {
  initial: { opacity: 0, backdropFilter: 'blur(0px)' },
  animate: { opacity: 1, backdropFilter: 'blur(18px)' },
  transition: { duration: 0.5, ease: EASE_OUT },
} as const;

// ── Reduced-motion helper ───────────────────────────────────────────────

/**
 * Check OS-level prefers-reduced-motion. Components can branch on this to
 * disable non-essential animation (scroll reveals, stagger). Critical motion
 * (tab indicators, loading spinners) stays on.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) {return false;}
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
