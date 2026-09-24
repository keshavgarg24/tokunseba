import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

// GitHub Pages serves a project repository under a subdirectory: this one lands at
// /tokunseba, not at the root. Every absolute path Next emits has to carry that prefix or
// the page loads and nothing on it does. Set it in the environment rather than here so the
// same build works at the root too, which is what a <name>.github.io repository, a custom
// domain, or Vercel would give you.
//
//   NEXT_PUBLIC_BASE_PATH=/tokunseba npm run build   -> keshavgarg24.github.io/tokunseba
//   npm run build                                    -> a site served from /
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

/** @type {import('next').NextConfig} */
const config = {
  output: 'export',
  reactStrictMode: true,
  basePath,
  // Written as a directory per route (`/docs/index.html` rather than `/docs.html`), which is
  // what a plain static host resolves correctly without rewrite rules.
  trailingSlash: true,
  images: { unoptimized: true },
  // There is a lockfile further up the tree on this machine and Next picks the outermost
  // one as the workspace root unless told otherwise.
  outputFileTracingRoot: import.meta.dirname,
  // Next regenerates AGENTS.md and CLAUDE.md in this directory on every dev start. The
  // repository already has its own at the root, so these are noise in `git status`.
  agentRules: false,
};

export default withMDX(config);
