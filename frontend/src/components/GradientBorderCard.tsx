import type { ReactNode } from 'react'

type Props = {
  children: ReactNode
  className?: string
  rounded?: 'md' | 'lg' | 'xl'
}

const radius = { md: 12, lg: 16, xl: 20 }

export function GradientBorderCard({ children, className = '', rounded = 'lg' }: Props) {
  return (
    <div
      className={`gradient-border ${className}`}
      style={{ borderRadius: radius[rounded] }}
    >
      <div className="relative p-5" style={{ borderRadius: radius[rounded] - 1 }}>
        {children}
      </div>
    </div>
  )
}
