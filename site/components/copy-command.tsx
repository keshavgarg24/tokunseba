'use client';
import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

export function CopyCommand({ cmd, className = '' }: { cmd: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border border-fd-border bg-fd-card px-4 py-2.5 font-mono text-sm ${className}`}
    >
      <span className="text-fd-primary select-none">$</span>
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
            // A browser that refuses the clipboard is not worth an error state. The
            // command is right there to select.
          }
        }}
      >
        {done ? <Check className="size-4 text-fd-primary" /> : <Copy className="size-4" />}
      </button>
    </div>
  );
}
