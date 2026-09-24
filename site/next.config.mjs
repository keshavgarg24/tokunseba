/** @type {import('next').NextConfig} */
const nextConfig = {
  // The whole site is static: no server code, no data fetching, no images to optimise.
  // Exporting means `out/` can be dropped on Vercel, Netlify, Cloudflare, GitHub Pages or
  // any web server, which matters for a project whose whole point is not depending on a
  // service you have to sign up for.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // There is a lockfile further up the tree on this machine, and Next picks the outermost
  // one as the workspace root unless told otherwise. Saying it explicitly keeps the build
  // reading this directory rather than a home directory that has nothing to do with it.
  outputFileTracingRoot: import.meta.dirname,
};
export default nextConfig;
