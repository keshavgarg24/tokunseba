import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  output: 'export',
  reactStrictMode: true,
  // There is a lockfile further up the tree on this machine and Next picks the outermost
  // one as the workspace root unless told otherwise.
  outputFileTracingRoot: import.meta.dirname,
};

export default withMDX(config);
