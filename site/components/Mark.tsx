type Props = { size?: number; className?: string; title?: string };

/**
 * The tokunseba mark. Two chevrons narrowing into a bar: wide context on the left, one
 * dense line on the right. It is the thing the project does, drawn once.
 */
export function Mark({ size = 24, className, title }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      role={title ? "img" : "presentation"}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <g
        fill="none"
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
        fill="none"
        stroke="var(--mark-accent, #3D7BE0)"
        strokeWidth={9}
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({ size = 22 }: { size?: number }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 9,
        fontWeight: 650,
        letterSpacing: "-.025em",
        fontSize: size >= 24 ? "1.15rem" : "1rem",
      }}
    >
      <Mark size={size} />
      tokunseba
    </span>
  );
}
