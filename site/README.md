# tokunseba.dev

The project website. Next.js 15 with the App Router, static export, no backend.

```bash
cd site
npm install
npm run dev      # http://127.0.0.1:3210
npm run build    # writes out/
```

`npm run build` produces a plain directory of files in `out/`, so it can be served by
Vercel, Netlify, Cloudflare Pages, GitHub Pages, or any web server that can hand back
static files. There is nothing to run and nothing to configure.

## What is in here

| Path | What it is |
|---|---|
| `app/page.tsx` | The whole page. Every section is in this one file, with its content in the arrays at the top. |
| `app/layout.tsx` | Metadata, and the two fonts, which are downloaded at build time and emitted into the bundle. |
| `app/globals.css` | The design tokens and every shared rule. The palette is the logo: ink, one blue, and nothing else unless it is saying something. |
| `components/Backdrop.tsx` | The mark drawing itself behind the hero, with tokens drifting through it. |
| `components/DashboardShot.tsx` | A drawn still of what `tokunseba dashboard` serves, rather than a screenshot that would go stale. |
| `components/Mark.tsx` | The logo, as a component. |
| `components/Nav.tsx`, `Copy.tsx` | The two pieces that need to run in the browser. |

## Rules it follows

- **Nothing is fetched at runtime.** No font host, no analytics, no CDN. The fonts are
  pulled once during the build and served from the same origin as the page. A site about
  not sending what you do not have to send should not open four connections to render a
  headline.
- **No claim appears here that is not true of the program.** Figures on this page are
  measured, and labelled as measurements rather than as promises.
- **Motion has an off switch.** Everything animated is inside a
  `prefers-reduced-motion` guard.
