'use client';
import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

const WAYS = [
  { id: 'pip', label: 'pip', cmd: 'pip install tokunseba' },
  { id: 'uv', label: 'uv', cmd: 'uv tool install tokunseba' },
  { id: 'pipx', label: 'pipx', cmd: 'pipx install tokunseba' },
];

/**
 * The install line, with the three ways people actually have.
 *
 * `pip` is first because it is the one that is already there. `uv` and `pipx` both put the
 * command on your path in an environment of its own, which is better, but telling somebody
 * to install a package manager before they can install your package is a step too many for
 * the first line of a page.
 */
export function Install({ compact = false }: { compact?: boolean }) {
  const [active, setActive] = useState(WAYS[0].id);
  const [done, setDone] = useState(false);
  const cmd = (WAYS.find((w) => w.id === active) ?? WAYS[0]).cmd;

  return (
    <div className="overflow-hidden rounded-xl border border-fd-border bg-fd-card text-start">
      <div className="flex border-b border-fd-border">
        {WAYS.map((w) => (
          <button
            key={w.id}
            type="button"
            onClick={() => setActive(w.id)}
            aria-selected={w.id === active}
            className={`px-4 py-2 text-xs font-medium transition-colors ${
              w.id === active
                ? 'border-b-2 border-fd-primary text-fd-foreground'
                : 'border-b-2 border-transparent text-fd-muted-foreground hover:text-fd-foreground'
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-3 px-4 py-3 font-mono text-sm">
        <span className="select-none text-fd-primary">$</span>
        <span className="truncate">{cmd}</span>
        <button
          type="button"
          aria-label="Copy command"
          className="ms-auto shrink-0 rounded-md p-1.5 text-fd-muted-foreground transition-colors hover:bg-fd-accent hover:text-fd-foreground"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(cmd);
              setDone(true);
              setTimeout(() => setDone(false), 1500);
            } catch {
              // A browser that refuses the clipboard is not an error state worth showing.
            }
          }}
        >
          {done ? <Check className="size-4 text-fd-primary" /> : <Copy className="size-4" />}
        </button>
      </div>
      {!compact ? (
        <p className="border-t border-fd-border px-4 py-2 text-xs text-fd-muted-foreground">
          {active === 'pip'
            ? 'Works anywhere Python does. Installs into whichever environment is active.'
            : `Puts tokunseba on your path in an environment of its own, so it cannot collide
               with the packages your projects depend on.`}
        </p>
      ) : null}
    </div>
  );
}
