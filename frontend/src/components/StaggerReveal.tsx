import { motion, type Variants } from 'framer-motion'
import { Children, type ReactNode } from 'react'

const container: Variants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.07, delayChildren: 0.04 },
  },
}

const item: Variants = {
  hidden: { opacity: 0, y: 16, filter: 'blur(4px)' },
  show: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
  },
}

type Props = {
  children: ReactNode
  className?: string
  once?: boolean
  amount?: number
}

export function StaggerReveal({ children, className = '', once = true, amount = 0.15 }: Props) {
  return (
    <motion.div
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once, amount }}
      className={className}
    >
      {Children.map(children, (child, idx) => (
        <motion.div key={idx} variants={item}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  )
}
