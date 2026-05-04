import { motion, useScroll, useSpring } from 'framer-motion'

export function ScrollProgress() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 200,
    damping: 30,
    restDelta: 0.001,
  })
  return (
    <motion.div
      aria-hidden
      className="fixed top-0 left-0 right-0 z-[60] h-[2px] origin-left"
      style={{
        scaleX,
        background: 'linear-gradient(90deg, #d4af37 0%, #f4d676 30%, #3b82f6 60%, #22c55e 100%)',
        boxShadow: '0 0 12px rgba(212,175,55,0.5)',
      }}
    />
  )
}
