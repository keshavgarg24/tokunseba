import styles from "./DashboardShot.module.css";

const DAYS = [34, 58, 41, 72, 63, 88, 51, 79, 94, 68, 83, 97, 74, 90];

const TOOLS = [
  { tool: "claude-code", req: "1,204", saved: "8.4M" },
  { tool: "codex", req: "386", saved: "2.1M" },
  { tool: "aider", req: "117", saved: "640k" },
];

const TOP = [
  { kind: "outline:python", was: "23k", now: "3.1k", handle: "h_4b91c07e" },
  { kind: "summary:pytest", was: "11.7k", now: "55", handle: "h_db4d5709" },
  { kind: "dedup_ref", was: "11.7k", now: "38", handle: "h_0f21a8c4" },
];

/**
 * A still of what `tokunseba dashboard` puts in a browser. Drawn rather than screenshotted
 * so it stays sharp at any size, reads correctly in a print stylesheet, and cannot go stale
 * against a design change on this page.
 */
export function DashboardShot() {
  const max = Math.max(...DAYS);
  const pts = DAYS.map((v, i) => {
    const x = (i * 560) / (DAYS.length - 1);
    const y = 92 - (v / max) * 78;
    return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");

  return (
    <div className={styles.page} aria-hidden="true">
      <div className={styles.top}>
        <span className={styles.brand}>
          <svg width="13" height="13" viewBox="0 0 64 64" fill="none">
            <g stroke="currentColor" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 13h21l13 19" /><path d="M5 51h21l13-19" /><path d="M5 32h34" />
            </g>
            <path d="M39 32h19" stroke="#3D7BE0" strokeWidth={9} strokeLinecap="round" />
          </svg>
          tokunseba
        </span>
        <span className={styles.live}><i />proxy on 127.0.0.1:7777</span>
        <span className={styles.seg}>
          <b>24h</b><b data-on="1">7d</b><b>30d</b>
        </span>
      </div>

      <div className={styles.hero}>
        <div className={styles.label}>Tokens never sent</div>
        <div className={styles.big}>
          11.2M <small>74.1% smaller</small>
        </div>
        <div className={styles.sub}>
          Across 1,707 requests in the last 7d, from 214 conversations in 6 projects.
          Every byte removed is still recoverable.
        </div>
        <dl className={styles.stats}>
          <div><dt>Requests</dt><dd>1,707</dd></div>
          <div><dt>Avg context</dt><dd>38k</dd></div>
          <div><dt>Peak request</dt><dd>163k</dd></div>
          <div><dt>Cache hits</dt><dd>81.4%</dd></div>
          <div><dt>Handles kept</dt><dd>942</dd></div>
        </dl>
      </div>

      <div className={styles.row3}>
        <div className={styles.tile}><span>Sent upstream</span><b>24.1M</b></div>
        <div className={styles.tile}><span>Fresh tokens</span><b>4.5M</b></div>
        <div className={styles.tile}><span>Substitutions</span><b>3,118</b></div>
        <div className={styles.tile}><span>Models</span><b>4</b></div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Tokens never sent, per day</div>
        <svg viewBox="0 0 560 96" preserveAspectRatio="none" className={styles.spark}>
          <defs>
            <linearGradient id="dsg" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3D7BE0" stopOpacity=".28" />
              <stop offset="100%" stopColor="#3D7BE0" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${pts} L560 96 L0 96 Z`} fill="url(#dsg)" />
          <path d={pts} fill="none" stroke="#3D7BE0" strokeWidth={2}
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </svg>
      </div>

      <div className={styles.row2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>By tool</div>
          <table>
            <tbody>
              {TOOLS.map((t) => (
                <tr key={t.tool}>
                  <td>{t.tool}</td>
                  <td className={styles.num}>{t.req}</td>
                  <td className={styles.num}><em>{t.saved}</em></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className={styles.card}>
          <div className={styles.cardTitle}>Biggest reductions</div>
          <table>
            <tbody>
              {TOP.map((t) => (
                <tr key={t.handle}>
                  <td><span className={styles.kind}>{t.kind}</span></td>
                  <td className={styles.num}>{t.was}</td>
                  <td className={styles.num}>{t.now}</td>
                  <td className={styles.mono}>{t.handle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
