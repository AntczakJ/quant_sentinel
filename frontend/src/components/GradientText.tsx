import type { ReactNode } from 'react'

type Props = {
  children: ReactNode
  className?: string
  as?: 'span' | 'h1' | 'h2' | 'h3' | 'p' | 'div'
}

export function GradientText({ children, className = '', as = 'span' }: Props) {
  const Tag = as as any
  return <Tag className={`gradient-text-flow ${className}`}>{children}</Tag>
}
