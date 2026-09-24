import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import { Provider } from '@/components/provider';
import { appName, appTagline } from '@/lib/shared';
import './global.css';

// Both faces are fetched once at build time and emitted into the bundle, so a reader's
// browser opens no connection to a font host. A site arguing for not sending what you do
// not have to send should not need four hosts to draw a headline.
const inter = Inter({ subsets: ['latin'], variable: '--font-sans', display: 'swap' });
const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
  weight: ['400', '500', '600'],
});

export const metadata: Metadata = {
  title: {
    default: `${appName} — a local proxy that shrinks what your coding agent sends`,
    template: `%s | ${appName}`,
  },
  description: appTagline,
  applicationName: appName,
  keywords: [
    'tokens', 'llm proxy', 'claude code', 'codex', 'context compression',
    'prompt cache', 'model routing', 'local first', 'anthropic', 'openai', 'ollama',
  ],
  openGraph: { title: appName, description: appTagline, type: 'website', siteName: appName },
  twitter: { card: 'summary_large_image', title: appName, description: appTagline },
  icons: { icon: '/logo.svg' },
};

export const viewport: Viewport = {
  themeColor: '#070a0f',
  width: 'device-width',
  initialScale: 1,
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${mono.variable} font-sans`}
      suppressHydrationWarning
    >
      <body className="flex flex-col min-h-screen">
        <Provider>{children}</Provider>
      </body>
    </html>
  );
}
