'use client';
import SearchDialog from '@/components/search';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { type ReactNode } from 'react';

export function Provider({ children }: { children: ReactNode }) {
  return (
    <RootProvider
      search={{ SearchDialog }}
      // Dark is the default here rather than the operating system's preference. This is a
      // tool you run in a terminal, next to a terminal, and the light theme is the one you
      // have to go and ask for. The toggle is still in the sidebar.
      theme={{ defaultTheme: 'dark', enableSystem: false }}
    >
      {children}
    </RootProvider>
  );
}
