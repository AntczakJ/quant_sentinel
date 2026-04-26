export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      className="transition-transform duration-300 group-hover:rotate-12"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="logo-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#d4af37" />
          <stop offset="50%" stopColor="#f4d676" />
          <stop offset="100%" stopColor="#a8861f" />
        </linearGradient>
      </defs>
      <rect width="100" height="100" rx="22" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
      <path
        d="M28 72 L50 28 L72 72 Z"
        fill="url(#logo-grad)"
        stroke="url(#logo-grad)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="50" cy="56" r="4.5" fill="#0a0a0c" />
    </svg>
  )
}
