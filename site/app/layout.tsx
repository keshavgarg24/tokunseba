import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Fetched once at build time and emitted into the bundle, so a visitor's browser never
// asks a font host for anything. The site is about not sending what you do not have to.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "600"],
  variable: "--font-mono",
});

const TITLE = "tokunseba";
const TAGLINE =
  "One local proxy in front of every AI coding tool on your machine. It shrinks each " +
  "request without losing a byte, and routes each turn to the model that turn actually needs.";

export const metadata: Metadata = {
  title: {
    default: "tokunseba, a local proxy that shrinks what your coding agent sends",
    template: "%s | tokunseba",
  },
  description: TAGLINE,
  applicationName: TITLE,
  keywords: [
    "tokens", "llm proxy", "claude code", "codex", "context compression",
    "prompt cache", "model routing", "local first", "openai", "anthropic", "ollama",
  ],
  authors: [{ name: "tokunseba contributors" }],
  openGraph: {
    title: "tokunseba",
    description: TAGLINE,
    type: "website",
    siteName: TITLE,
  },
  twitter: { card: "summary_large_image", title: TITLE, description: TAGLINE },
  icons: { icon: "/logo.svg" },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#FAFAFA",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
