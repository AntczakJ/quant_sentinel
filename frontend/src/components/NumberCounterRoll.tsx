import { useEffect, useRef } from 'react'
import { motion, useInView, useMotionValue, useSpring, useTransform } from 'framer-motion'

type Props = {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
  duration?: number
}

export function NumberCounterRoll({
  value,
  decimals = 0,
  prefix = '',
  suffix = '',
  className = '',
  duration = 1.2,
}: Props) {
  const ref = useRef<HTMLSpanElement | null>(null)
  const inView = useInView(ref, { once: true, margin: '-10%' })
  const mv = useMotionValue(0)
  const spring = useSpring(mv, { stiffness: 60, damping: 18, duration: duration * 1000 })
  const display = useTransform(spring, (v) =>
    `${prefix}${v.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}${suffix}`,
  )

  useEffect(() => {
    if (inView) mv.set(value)
  }, [inView, value, mv])

  return (
    <motion.span ref={ref} className={`num ${className}`}>
      {display}
    </motion.span>
  )
}
