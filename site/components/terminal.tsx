import type { ReactNode } from 'react';

/** A framed block of terminal output. No chrome dots, no window title bar, no gloss. */
export function Terminal({
  label,
  children,
  className = '',
}: {
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`overflow-hidden rounded-xl border border-fd-border bg-fd-card ${className}`}>
      {label ? (
        <div className="flex items-center gap-2 border-b border-fd-border px-4 py-2.5">
          <span className="size-1.5 rounded-full bg-fd-primary" />
          <span className="font-mono text-xs text-fd-muted-foreground">{label}</span>
        </div>
      ) : null}
      <pre className="tk-term overflow-x-auto px-4 py-3.5">{children}</pre>
    </div>
  );
}

export const K = ({ children }: { children: ReactNode }) => (
  <span className="text-fd-foreground font-medium">{children}</span>
);
export const C = ({ children }: { children: ReactNode }) => (
  <span className="text-fd-muted-foreground">{children}</span>
);
export const B = ({ children }: { children: ReactNode }) => (
  <span className="text-fd-primary">{children}</span>
);
export const G = ({ children }: { children: ReactNode }) => (
  <span className="text-emerald-400">{children}</span>
);
