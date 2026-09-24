'use client';
import { useState, type ReactNode } from 'react';

export type Surface = {
  id: string;
  tab: string;
  eyebrow: string;
  title: string;
  body: string;
  code: ReactNode;
};

export function Surfaces({ items }: { items: Surface[] }) {
  const [active, setActive] = useState(items[0].id);
  const current = items.find((i) => i.id === active) ?? items[0];

  return (
    <div>
      <div
        role="tablist"
        aria-label="Ways to run tokunseba"
        className="inline-flex flex-wrap gap-1 rounded-lg border border-fd-border bg-fd-card p-1"
      >
        {items.map((i) => (
          <button
            key={i.id}
            role="tab"
            aria-selected={i.id === active}
            onClick={() => setActive(i.id)}
            className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              i.id === active
                ? 'bg-fd-primary text-fd-primary-foreground'
                : 'text-fd-muted-foreground hover:text-fd-foreground'
            }`}
          >
            {i.tab}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-2 lg:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fd-muted-foreground">
            {current.eyebrow}
          </p>
          <h3 className="mt-2 text-xl font-semibold tracking-tight">{current.title}</h3>
          <p className="mt-3 text-fd-muted-foreground">{current.body}</p>
        </div>
        <div>{current.code}</div>
      </div>
    </div>
  );
}
