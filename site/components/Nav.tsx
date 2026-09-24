"use client";

import { useEffect, useState } from "react";
import { Wordmark } from "./Mark";
import styles from "./Nav.module.css";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#reading", label: "Reading files" },
  { href: "#routing", label: "Routing" },
  { href: "#dashboard", label: "Dashboard" },
  { href: "#commands", label: "Commands" },
];

export const REPO = "https://github.com/keshavgarg24/tokunseba";

export function Nav() {
  const [stuck, setStuck] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setStuck(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`${styles.bar} ${stuck ? styles.stuck : ""}`}>
      <div className={`shell ${styles.inner}`}>
        <a href="#top" className={styles.brand} aria-label="tokunseba, back to the top">
          <Wordmark size={24} />
        </a>

        <nav className={`${styles.links} ${open ? styles.open : ""}`}>
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={() => setOpen(false)}>
              {l.label}
            </a>
          ))}
        </nav>

        <div className={styles.right}>
          <a
            className={styles.repo}
            href={REPO}
            target="_blank"
            rel="noreferrer noopener"
            aria-label="tokunseba on GitHub"
          >
            <svg width="19" height="19" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 0a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38l-.01-1.34c-2.23.48-2.7-1.07-2.7-1.07-.36-.93-.89-1.18-.89-1.18-.73-.5.05-.49.05-.49.81.06 1.23.83 1.23.83.72 1.23 1.89.87 2.35.67.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.03 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48l-.01 2.2c0 .21.15.46.55.38A8 8 0 0 0 8 0Z" />
            </svg>
          </a>
          <a className="btn btn-primary" href="#install">
            Install
          </a>
          <button
            className={styles.burger}
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label="Menu"
          >
            <span /><span /><span />
          </button>
        </div>
      </div>
    </header>
  );
}
