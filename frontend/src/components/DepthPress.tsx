import { useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'

type Props = {
  children: ReactNode
  variant?: 'gold' | 'ghost' | 'bull' | 'bear'
  className?: string
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  title?: string
  'aria-label'?: string
}

/**
 * DepthPress — premium tactile button.
 *
 * Three layered effects:
 *   1. Inset shadow (top-light + bottom-dark) — gives 3D depth
 *   2. Spring scale on press (1 → 0.97)
 *   3. Hover glow + shimmer overlay
 *
 * Used as the "primary action" button. Pairs with sound feedback
 * (playClick from @/lib/sound). Looks like an Apple buttoned-leather
 * surface — top-tier 2026 standard.
 */
export function DepthPress({
  children,
  variant = 'gold',
  className = '',
  onClick,
  ...rest
}: Props) {
  const [pressing, setPressing] = useState(false)

  const variantClasses: Record<string, string> = {
    gold: 'bg-gradient-to-b from-gold-400 to-gold-600 text-ink-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.3),inset_0_-1px_0_rgba(0,0,0,0.2),0_8px_24px_rgba(212,175,55,0.25)]',
    ghost: 'bg-white/[0.04] border border-white/[0.08] text-ink-800 backdrop-blur-md shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]',
    bull: 'bg-gradient-to-b from-bull to-green-700 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_8px_24px_rgba(34,197,94,0.25)]',
    bear: 'bg-gradient-to-b from-bear to-red-700 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_8px_24px_rgba(239,68,68,0.25)]',
  }

  return (
    <motion.button
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.97, y: 0 }}
      transition={{ type: 'spring', stiffness: 400, damping: 22 }}
      onMouseDown={() => setPressing(true)}
      onMouseUp={() => setPressing(false)}
      onMouseLeave={() => setPressing(false)}
      onClick={(e) => {
        try {
          import('@/lib/sound').then((m) => m.isSoundEnabled() && m.playClick())
        } catch {/* noop */}
        onClick?.(e)
      }}
      className={`relative overflow-hidden rounded-full px-5 py-2.5 text-body font-medium transition-shadow duration-150 ${variantClasses[variant]} ${className}`}
      {...rest}
    >
      {/* Hover shimmer */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 translate-x-[-100%] bg-gradient-to-r from-transparent via-white/20 to-transparent transition-transform duration-700 group-hover:translate-x-[100%]"
      />
      <span className="relative">{children}</span>
      {/* Pressed-state highlight */}
      {pressing && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-black/10"
        />
      )}
    </motion.button>
  )
}
