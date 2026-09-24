import styles from './backdrop.module.css';

/** The mark behind the hero. See the stylesheet for what moves and what deliberately does not. */
export function Backdrop() {
  return (
    <div className={styles.wrap} aria-hidden="true">
      <svg className={styles.mark} viewBox="0 0 64 64" fill="none">
        <g
          stroke="currentColor"
          strokeWidth={5}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M5 13h21l13 19" />
          <path d="M5 51h21l13-19" />
          <path d="M5 32h34" />
        </g>
        <path
          className={styles.bar}
          d="M39 32h19"
          stroke="var(--tk-blue-bright)"
          strokeWidth={7}
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
