import type { ReactNode } from 'react'

type Props = {
  children: ReactNode
  speed?: 'slow' | 'normal'
  className?: string
  pauseOnHover?: boolean
}

export function Marquee({ children, speed = 'normal', className = '', pauseOnHover = true }: Props) {
  const animClass = speed === 'slow' ? 'animate-marquee-slow' : 'animate-marquee'
  return (
    <div className={`marquee-mask group flex w-full overflow-hidden ${className}`}>
      <div
        className={`flex shrink-0 items-center gap-8 pr-8 ${animClass} ${pauseOnHover ? 'group-hover:[animation-play-state:paused]' : ''}`}
      >
        {children}
      </div>
      <div
        aria-hidden
        className={`flex shrink-0 items-center gap-8 pr-8 ${animClass} ${pauseOnHover ? 'group-hover:[animation-play-state:paused]' : ''}`}
      >
        {children}
      </div>
    </div>
  )
}
