# The tokunseba website

Landing page and documentation. [Fumadocs](https://fumadocs.dev) on Next.js, static export,
no backend.

```bash
cd site
npm install
npm run dev              # http://localhost:3000
npm run build            # writes out/
npx serve out            # serve the built output
```

`npm run build` produces a plain directory of files in `out/`, so it can be served by
Vercel, Netlify, Cloudflare Pages, GitHub Pages, or any web server. There is nothing to run
and nothing to configure.

Requires Node 20.19 or newer.

## Layout

| Path | What it is |
|---|---|
| `app/(home)/page.tsx` | The landing page |
| `app/docs/` | The documentation shell, from Fumadocs |
| `app/global.css` | The palette and the few rules that are not Fumadocs' own |
| `content/docs/**/*.mdx` | Every documentation page |
| `content/docs/**/meta.json` | Sidebar ordering and section titles |
| `components/` | The landing page's own pieces |
| `lib/shared.ts` | App name, repository, PyPI link |

## Rules it follows

- **Dark by default**, with a toggle. This is a tool you run in a terminal, next to a
  terminal.
- **Nothing is fetched at runtime.** Both fonts are pulled once during the build and served
  from the same origin as the page. No analytics, no CDN. A site arguing for not sending what
  you do not have to send should not open four connections to draw a headline.
- **No claim here that is not true of the program.** Figures are measured, and labelled as
  measurements rather than as promises.
- **`content/docs/reference/commands.mdx` is generated** from the command definitions
  themselves, so it cannot drift from what the tool accepts. Regenerate it after adding or
  changing a command.

## Search

Fumadocs' static Orama index, built at `out/api/search` and downloaded by the client on first
use. No search service, no API key, nothing to keep running.
