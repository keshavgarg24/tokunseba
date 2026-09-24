# The tokunseba website

Landing page and documentation. [Fumadocs](https://fumadocs.dev) on Next.js, static export,
no backend.

```bash
cd site
nvm use                  # there is an .nvmrc
npm install
npm run dev              # http://localhost:3000
npm run build            # writes out/
npm run preview          # build, then serve out/
```

`npm run build` produces a plain directory of files in `out/`, so it can be served by
Vercel, Netlify, Cloudflare Pages, GitHub Pages, or any web server. There is nothing to run
and nothing to configure.

## Node 20.19 or newer

Not optional, and the reason is worth knowing. Fumadocs' MDX loader is an ES module and Next
loads it with `require()`. Node only permits that from **20.19.0** and **22.12.0** onward. On
anything older the build dies inside `node_modules` with a `require() of ES Module ... not
supported` trace that says nothing about what to do.

`npm run dev` and `npm run build` check the version first and print an actionable message
instead, and `engines` in package.json makes npm warn at install time.

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
- **The version on the landing page is read from `../pyproject.toml` at build time**
  (`lib/version.ts`), so it cannot be left behind by a release. When the site is built
  outside the repository the pill simply does not show a version.
- **Install instructions lead with `pip`**, because that is the one everybody already has.
  `uv` and `pipx` are offered next to it rather than instead of it.

## Search

Fumadocs' static Orama index, built at `out/api/search` and downloaded by the client on first
use. No search service, no API key, nothing to keep running.

## Deploying

The build is a directory of static files. Two paths are set up.

### GitHub Pages, automatically

`.github/workflows/pages.yml` builds and publishes on every push to `main` that touches
`site/`. One-time setup, once only:

> **Settings → Pages → Source → GitHub Actions**

After that the site is at `https://keshavgarg24.github.io/tokunseba/` and nothing else is
needed. The workflow builds with `NEXT_PUBLIC_BASE_PATH=/tokunseba`, because GitHub serves a
project repository from a subdirectory and every absolute path Next emits has to carry that
prefix or the page loads and nothing on it works.

### Vercel

Import the repository and set **Root Directory** to `site`. Everything else is detected.
Leave `NEXT_PUBLIC_BASE_PATH` unset: a Vercel deployment is served from `/`, so the site
should be built without a prefix, which is the default.

### Anywhere else

```bash
npm run build     # writes out/
```

Copy `out/` to any web server. `trailingSlash` is on, so every route is a directory with its
own `index.html` and no rewrite rules are needed.

### The one thing to watch

The static search index is downloaded by the browser from an absolute URL. Under a base path
it lives at `<basePath>/api/search`, and the default of `/api/search` 404s **silently** --
the dialog opens, takes what you type, and returns nothing. `components/search.tsx` reads
`NEXT_PUBLIC_BASE_PATH` for exactly this reason. If you add another base path, that is the
file to check.
