import { useEffect, useRef } from 'react'

type Props = {
  className?: string
  size?: number
  color?: string
}

export function Spotlight({
  className = '',
  size = 380,
  color = 'rgba(212,175,55,0.16)',
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const parent = el.parentElement
    if (!parent) return

    const onMove = (e: MouseEvent) => {
      const rect = parent.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      el.style.setProperty('--sx', `${x}px`)
      el.style.setProperty('--sy', `${y}px`)
      el.style.opacity = '1'
    }
    const onLeave = () => {
      el.style.opacity = '0'
    }

    parent.addEventListener('mousemove', onMove)
    parent.addEventListener('mouseleave', onLeave)
    return () => {
      parent.removeEventListener('mousemove', onMove)
      parent.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  return (
    <div
      ref={ref}
      aria-hidden
      className={`pointer-events-none absolute inset-0 transition-opacity duration-500 ${className}`}
      style={{
        opacity: 0,
        background: `radial-gradient(${size}px circle at var(--sx, -200px) var(--sy, -200px), ${color}, transparent 75%)`,
      }}
    />
  )
}
