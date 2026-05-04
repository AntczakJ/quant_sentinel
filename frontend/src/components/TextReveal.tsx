import { motion, type Variants } from 'framer-motion'

type Props = {
  text: string
  className?: string
  delay?: number
  splitBy?: 'word' | 'char'
}

const container = (delay: number, stagger: number): Variants => ({
  hidden: {},
  show: { transition: { delayChildren: delay, staggerChildren: stagger } },
})

const item: Variants = {
  hidden: { y: '100%', opacity: 0, filter: 'blur(6px)' },
  show: {
    y: 0,
    opacity: 1,
    filter: 'blur(0px)',
    transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] },
  },
}

export function TextReveal({ text, className = '', delay = 0, splitBy = 'word' }: Props) {
  const tokens = splitBy === 'word' ? text.split(' ') : text.split('')
  const stagger = splitBy === 'word' ? 0.06 : 0.018

  return (
    <motion.span
      variants={container(delay, stagger)}
      initial="hidden"
      animate="show"
      className={`inline-flex flex-wrap ${className}`}
    >
      {tokens.map((tok, i) => (
        <span
          key={i}
          className="relative inline-block overflow-hidden align-bottom"
          style={{ marginRight: splitBy === 'word' ? '0.25em' : 0 }}
        >
          <motion.span variants={item} className="inline-block">
            {tok === ' ' ? ' ' : tok}
          </motion.span>
        </span>
      ))}
    </motion.span>
  )
}
