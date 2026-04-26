import { type ReactNode } from 'react'
import { motion } from 'framer-motion'

interface CardProps {
  children: ReactNode
  className?: string
  variant?: 'flat' | 'raised' | 'interactive'
  delay?: number
}

export function Card({ children, className = '', variant = 'raised', delay = 0 }: CardProps) {
  const surfaceClass =
    variant === 'flat'
      ? 'surface'
      : variant === 'interactive'
      ? 'surface-interactive'
      : 'surface-raised'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
      className={`${surfaceClass} rounded-xl2 ${className}`}
    >
      {children}
    </motion.div>
  )
}
