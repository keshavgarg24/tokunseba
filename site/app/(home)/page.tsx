import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { CopyCommand } from '@/components/copy-command';
import { Surfaces, type Surface } from '@/components/surfaces';
import { B, C, G, K, Terminal } from '@/components/terminal';
import { repoUrl } from '@/lib/shared';

const PROPERTIES = [
  {
    t: 'It runs on your machine',
    d: 'No account, no sign in, no telemetry. The only outbound traffic is the request your tool was already making, to the provider it already chose.',
  },
  {
    t: 'It does not lose anything',
    d: 'Every removal is content addressed and stored locally. Expand a handle and the original comes back byte for byte, failures and stack traces still in it.',
  },
  {
    t: 'It measures itself',
    d: 'Sessions are split at random into a control arm and a treatment arm, both in the same ledger, so you can check the claim against your own traffic.',
  },
];

const SURFACES: Surface[] = [
  {
    id: 'proxy',
    tab: 'Proxy',
    eyebrow: 'Every tool at once',
    title: 'Point everything at it and carry on',
    body: 'One command finds the AI tools on this machine, backs up every file it touches, points them at the proxy and starts it in the background. It prints each change before making it, and one command puts it all back.',
    code: (
      <Terminal label="setup">
        <C>$ </C><K>tokunseba init</K>{'\n\n'}
        <C>  claude-code   </C>ANTHROPIC_BASE_URL {'->'} 127.0.0.1:7777{'\n'}
        <C>  codex         </C>model_provider = &quot;tokunseba&quot;{'\n'}
        <C>  shell-env     </C>env block added to ~/.zshrc{'\n'}
        <C>  backups       </C>~/.tokunseba/backups{'\n\n'}
        <G>  proxy running on 127.0.0.1:7777</G>{'\n\n'}
        <C>$ </C><K>tokunseba doctor</K>{'\n'}
        <G>  ok  </G>proxy reachable{'\n'}
        <G>  ok  </G>tool: claude-code{'\n'}
        <G>  ok  </G>tool: codex
      </Terminal>
    ),
  },
  {
    id: 'wrap',
    tab: 'Wrap',
    eyebrow: 'One tool, nothing configured',
    title: 'Run a single tool through it',
    body: 'No config file is written and nothing on the machine changes. The tool is launched with the proxy in its environment for that run only, which is the right way to try it.',
    code: (
      <Terminal label="one run">
        <C>$ </C><K>tokunseba wrap claude</K>{'\n'}
        <C>$ </C><K>tokunseba wrap codex</K>{'\n'}
        <C>$ </C><K>tokunseba wrap aider</K>{'\n\n'}
        <C># anything else</C>{'\n'}
        <C>$ </C><K>tokunseba wrap-any -- my-agent --flag</K>{'\n\n'}
        <C># or just compress one command&apos;s output</C>{'\n'}
        <C>$ </C><K>tokunseba run -- pytest -q</K>
      </Terminal>
    ),
  },
  {
    id: 'library',
    tab: 'Library',
    eyebrow: 'Python',
    title: 'Call the same pipeline directly',
    body: 'For a LangChain callback, a LiteLLM hook, an ASGI middleware, or a script that assembles its own request. Same pipeline, same ledger, same handle store, so a handle minted from Python expands from the command line.',
    code: (
      <Terminal label="python">
        <B>from</B> tokunseba <B>import</B> compress, shrink, expand{'\n\n'}
        out = compress(body, protocol=<G>&quot;openai&quot;</G>){'\n'}
        print(out.saved, out.ratio){'\n'}
        send(out.body){'\n\n'}
        text = shrink(log, command=<G>&quot;pytest -q&quot;</G>){'\n'}
        code = shrink(source, path=<G>&quot;client.py&quot;</G>){'\n\n'}
        original = expand(<G>&quot;h_4b91c07e&quot;</G>)
      </Terminal>
    ),
  },
  {
    id: 'mcp',
    tab: 'MCP',
    eyebrow: 'Agents without a shell',
    title: 'Expose recovery as a tool',
    body: 'An agent that cannot run commands can still ask for the full text behind any handle. The MCP server exposes expand over stdio, so the reach is preserved even where a terminal is not available.',
    code: (
      <Terminal label="mcp">
        <C>$ </C><K>tokunseba mcp</K>{'\n\n'}
        <C># or register it during setup</C>{'\n'}
        <C>$ </C><K>tokunseba init --with-mcp</K>{'\n\n'}
        <C>  tool  </C>expand(handle){'\n'}
        <C>        </C>returns the original text behind{'\n'}
        <C>        </C>a tokunseba handle, byte for byte
      </Terminal>
    ),
  },
];

const REMOVED = [
  ['A file read twice', 'The second copy becomes a pointer to the first', 'dedup_ref'],
  ['A file read again after an edit', 'Only the diff since the model last saw it', 'diff_ref'],
  ['A long source file', 'Imports, signatures, decorators and docstrings kept; bodies folded', 'outline'],
  ['A test or build run', 'What failed, the assertion text and the counts', 'summary'],
  ['A lock file or a bundle', 'One line describing what it was', 'junk'],
  ['Terminal escapes and progress bars', 'Removed losslessly, nothing else touched', 'canonical'],
];

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col">
      {/* ------------------------------------------------------------- hero */}
      <section className="relative overflow-hidden border-b border-fd-border">
        <div className="tk-grid-bg" />
        <div className="tk-shell relative py-20 text-center sm:py-28">
          <Link
            href="/docs"
            className="inline-flex items-center gap-2 rounded-full border border-fd-border bg-fd-card px-3.5 py-1.5 text-xs text-fd-muted-foreground transition-colors hover:text-fd-foreground"
          >
            <span className="size-1.5 rounded-full bg-fd-primary" />
            v0.1.2 is on PyPI
            <ArrowRight className="size-3" />
          </Link>

          <h1 className="tk-display mx-auto mt-7 max-w-4xl text-balance">
            Send less.
            <br />
            <span className="text-fd-primary">Lose nothing.</span>
          </h1>

          <p className="mx-auto mt-7 max-w-2xl text-balance text-lg text-fd-muted-foreground">
            One local proxy in front of every AI coding tool on your machine. It shrinks each
            request without losing a byte, keeps the prompt cache intact, and can send a turn
            to the model that turn actually needs.
          </p>

          <div className="mx-auto mt-9 max-w-md">
            <CopyCommand cmd="uv tool install tokunseba" />
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/docs"
              className="inline-flex items-center gap-2 rounded-lg bg-fd-primary px-4 py-2.5 text-sm font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
            >
              Read the documentation
              <ArrowRight className="size-4" />
            </Link>
            <a
              href={repoUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-2 rounded-lg border border-fd-border px-4 py-2.5 text-sm font-medium transition-colors hover:bg-fd-accent"
            >
              Source on GitHub
            </a>
          </div>

          <p className="mt-6 text-xs text-fd-muted-foreground">
            Python 3.12 to 3.14 &middot; macOS, Linux and Windows &middot; MIT licensed
          </p>
        </div>
      </section>

      {/* --------------------------------------------------------- properties */}
      <section className="border-b border-fd-border">
        <div className="tk-shell grid sm:grid-cols-3 sm:divide-x sm:divide-fd-border">
          {PROPERTIES.map((p) => (
            <div key={p.t} className="py-10 sm:px-7 sm:first:ps-0 sm:last:pe-0">
              <h2 className="text-base font-semibold tracking-tight">{p.t}</h2>
              <p className="mt-2 text-sm leading-relaxed text-fd-muted-foreground">{p.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ what it does */}
      <section className="tk-shell py-20 sm:py-24">
        <div className="grid gap-10 lg:grid-cols-2 lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fd-primary">
              What it removes
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-balance">
              Almost none of your context is your thinking
            </h2>
            <p className="mt-4 text-fd-muted-foreground">
              An agent reads a file, runs the tests, lists a directory, reads the file again,
              and carries the whole transcript forward on every call. The question you typed is
              a few hundred tokens. What surrounds it is tens of thousands, and most of that is
              text the model has already seen or never needed.
            </p>
            <Link
              href="/docs/how-it-works"
              className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-fd-primary hover:underline"
            >
              How the pipeline decides
              <ArrowRight className="size-3.5" />
            </Link>
          </div>

          <Terminal label="tokunseba top">
            <C>where the tokens went          was     now</C>{'\n'}
            <B>outline:python</B>{'               23k    3.1k'}{'\n'}
            <B>summary:pytest</B>{'             11.7k      55'}{'\n'}
            <B>dedup_ref</B>{'                  11.7k      38'}{'\n'}
            <B>junk:lockfile</B>{'              8.4k      31'}{'\n\n'}
            <C>what could not be helped</C>{'\n'}
            passthrough{'  6.6k  '}<C>a first read of a short file</C>{'\n'}
            passthrough{'  4.9k  '}<C>prose the model has to see</C>
          </Terminal>
        </div>

        <div className="mt-12 overflow-hidden rounded-xl border border-fd-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-fd-border bg-fd-muted/40 text-left">
                <th className="px-5 py-3 font-medium text-fd-muted-foreground">Arrives as</th>
                <th className="px-5 py-3 font-medium text-fd-muted-foreground">Goes out as</th>
                <th className="px-5 py-3 font-medium text-fd-muted-foreground">Recorded</th>
              </tr>
            </thead>
            <tbody>
              {REMOVED.map(([a, b, k]) => (
                <tr key={k} className="border-b border-fd-border last:border-0">
                  <td className="px-5 py-3">{a}</td>
                  <td className="px-5 py-3 text-fd-muted-foreground">{b}</td>
                  <td className="px-5 py-3 font-mono text-xs text-fd-primary">{k}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* -------------------------------------------------------------- surfaces */}
      <section className="border-y border-fd-border bg-fd-muted/20">
        <div className="tk-shell py-20 sm:py-24">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fd-primary">
            Four ways in
          </p>
          <h2 className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight text-balance">
            Use it whichever way fits what you already run
          </h2>
          <p className="mt-4 max-w-2xl text-fd-muted-foreground">
            The same pipeline behind every one of them, writing to the same ledger and the same
            handle store.
          </p>
          <div className="mt-10">
            <Surfaces items={SURFACES} />
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- routing */}
      <section className="tk-shell py-20 sm:py-24">
        <div className="grid gap-10 lg:grid-cols-2 lg:items-center">
          <Terminal label="routing across protocols" className="lg:order-2">
            <C>$ </C><K>tokunseba models add deepseek https://api.deepseek.com</K>{'\n'}
            <C>$ </C><K>tokunseba route add --domain devops \</K>{'\n'}
            <K>        --to ollama --model qwen3-coder:30b</K>{'\n'}
            <C>$ </C><K>tokunseba route enable</K>{'\n\n'}
            <C>$ </C><K>tokunseba route test &quot;bump the docker base image&quot;</K>{'\n\n'}
            {'  domain      devops      '}<C>confidence 0.88</C>{'\n'}
            {'  difficulty  trivial     '}<C>confidence 0.45  discarded</C>{'\n'}
            {'  sensitive   no'}{'\n'}
            <G>  would go to ollama / qwen3-coder:30b</G>{'\n'}
            <C>  arrives as anthropic, translated on the way out</C>{'\n'}
            <C>  and translated back on the way home</C>{'\n'}
            <C>  nothing was sent.</C>
          </Terminal>

          <div className="lg:order-1">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fd-primary">
              Routing
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-balance">
              The right model for the turn, across protocols
            </h2>
            <p className="mt-4 text-fd-muted-foreground">
              Claude Code speaks Anthropic to everything. Codex speaks OpenAI. That is why
              &ldquo;send the easy turns to the local model&rdquo; is usually a slide rather
              than a feature: the client cannot address the other endpoint and the other
              endpoint cannot read the client.
            </p>
            <p className="mt-4 text-fd-muted-foreground">
              tokunseba rewrites the turn instead. System prompts, tool definitions, tool calls
              and their results, images, stop reasons and usage are all mapped, and a streamed
              reply is rebuilt event by event rather than buffered.
            </p>
            <Link
              href="/docs/routing"
              className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-fd-primary hover:underline"
            >
              How routing decides
              <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------- cta */}
      <section className="border-t border-fd-border">
        <div className="tk-shell py-20 text-center sm:py-24">
          <h2 className="mx-auto max-w-xl text-3xl font-semibold tracking-tight text-balance">
            Point your tools at it and keep working
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-fd-muted-foreground">
            One command configures every supported tool, backs up every file it touches, and
            starts the proxy in the background. <code>tokunseba off</code> puts it all back.
          </p>
          <div className="mx-auto mt-8 grid max-w-md gap-2.5">
            <CopyCommand cmd="uv tool install tokunseba" />
            <CopyCommand cmd="tokunseba init" />
          </div>
          <Link
            href="/docs/install"
            className="mt-7 inline-flex items-center gap-2 rounded-lg bg-fd-primary px-4 py-2.5 text-sm font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
          >
            Installation guide
            <ArrowRight className="size-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
