export function Mark({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      aria-hidden="true"
      fill="none"
    >
      <g
        stroke="currentColor"
        strokeWidth={6.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M5 13h21l13 19" />
        <path d="M5 51h21l13-19" />
        <path d="M5 32h34" />
      </g>
      <path
        d="M39 32h19"
        stroke="var(--tk-blue-bright)"
        strokeWidth={9}
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <Mark size={20} />
      tokunseba
    </span>
  );
}
