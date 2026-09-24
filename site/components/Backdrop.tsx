import styles from "./Backdrop.module.css";

/**
 * The mark, drawn very large behind the hero, tracing itself on a slow loop, with tokens
 * drifting through it: wide and grey going in on the left, narrow and blue coming out on
 * the right. The logo is already a picture of that, so the animation is the logo doing
 * the thing rather than decoration sitting next to it.
 *
 * Every value here is fixed rather than random. A random one would differ between the
 * server render and the client render, and React would throw away the markup and redraw
 * the whole hero on load.
 */
const IN = [
  { top: 14, w: 72, dur: 9.4, delay: -1.2 },
  { top: 27, w: 46, dur: 11.2, delay: -6.1 },
  { top: 38, w: 88, dur: 8.6, delay: -3.4 },
  { top: 52, w: 58, dur: 12.1, delay: -8.7 },
  { top: 63, w: 104, dur: 10.3, delay: -0.4 },
  { top: 74, w: 40, dur: 9.9, delay: -5.2 },
  { top: 86, w: 66, dur: 11.8, delay: -2.6 },
];

const OUT = [
  { top: 22, w: 16, dur: 8.9, delay: -4.3 },
  { top: 44, w: 11, dur: 10.6, delay: -7.5 },
  { top: 58, w: 19, dur: 9.2, delay: -1.9 },
  { top: 80, w: 13, dur: 11.4, delay: -6.8 },
];

export function Backdrop() {
  return (
    <div className={styles.backdrop} aria-hidden="true">
      <svg className={styles.glyph} viewBox="0 0 64 64" fill="none">
        <g
          stroke="#FFFFFF"
          strokeWidth={3.4}
          strokeLinecap="round"
          strokeLinejoin="round"
          className={styles.trace}
        >
          <path d="M5 13h21l13 19" />
          <path d="M5 51h21l13-19" />
          <path d="M5 32h34" />
        </g>
        <path
          d="M39 32h19"
          stroke="#7FB0FF"
          strokeWidth={5}
          strokeLinecap="round"
          className={styles.bar}
        />
      </svg>

      <div className={styles.stream}>
        {IN.map((t, i) => (
          <i
            key={`i${i}`}
            className={styles.tok}
            style={{
              top: `${t.top}%`,
              width: t.w,
              animationDuration: `${t.dur}s`,
              animationDelay: `${t.delay}s`,
            }}
          />
        ))}
        {OUT.map((t, i) => (
          <i
            key={`o${i}`}
            className={`${styles.tok} ${styles.clean}`}
            style={{
              top: `${t.top}%`,
              width: t.w,
              animationDuration: `${t.dur}s`,
              animationDelay: `${t.delay}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
