import { Backdrop } from "@/components/Backdrop";
import { Copy } from "@/components/Copy";
import { DashboardShot } from "@/components/DashboardShot";
import { Mark, Wordmark } from "@/components/Mark";
import { Nav, REPO } from "@/components/Nav";
import s from "@/components/Sections.module.css";

const TIERS = [
  {
    n: 0, name: "Observe", state: "always on",
    may: "Nothing. Every byte is forwarded exactly as your tool sent it.",
    does: "Counts tokens, records what the prompt cache did, writes the ledger.",
  },
  {
    n: 1, name: "Reversible", state: "on",
    may: "Tool results only.",
    does: "Strips terminal escape codes and progress bar spam. Replaces a repeated result with a pointer, and a re-read file with the diff since you last saw it. Adds cache breakpoints clients forgot.",
  },
  {
    n: 2, name: "Reach preserving", state: "on",
    may: "The shape of a long tool result.",
    does: "Summarises test, build and install output down to what failed. Folds the bodies out of a source file. Replaces lock files and binaries with one line. Everything keeps a handle to the full text.",
  },
  {
    n: 3, name: "Opt in", state: "off",
    may: "Which model answers, and the text of a request.",
    does: "Routes a turn to a smaller or local model, redacts credentials before they leave, labels tool results that look like prompt injection. Off until you turn it on.",
  },
];

const FEATURES = [
  {
    t: "Outlined files, not truncated ones",
    d: "A 2,000 line module comes through with every import, class, signature, decorator, docstring and constant intact, and each long body replaced by one line naming the handle that holds it.",
  },
  {
    t: "Repeats become pointers",
    d: "The same tool result sent twice is sent once. The second copy is a reference to the first, and the reference is only used when it is genuinely smaller than what it replaces.",
  },
  {
    t: "Re-reads become diffs",
    d: "A file read again after an edit arrives as the change since the model last saw it, not as the file.",
  },
  {
    t: "Failures survive summarising",
    d: "A pytest run of nine hundred lines becomes the failures, the assertion text and the counts. The line that says FAILED is never the line that gets dropped.",
  },
  {
    t: "Cache breakpoints, added and watched",
    d: "Clients that forget to mark a cacheable prefix get one. When a client puts a timestamp inside its own cached prefix, the ledger names the region that drifted and why.",
  },
  {
    t: "Nothing is destroyed",
    d: "Whatever is left out is stored behind a handle. tokunseba expand returns it byte for byte, and an MCP tool exposes the same thing to agents without a shell.",
  },
];

const COMMANDS = [
  {
    group: "Setting up",
    items: [
      ["tokunseba init", "Point every supported tool at the proxy and start it in the background"],
      ["tokunseba doctor", "Check the install, and anything quietly sending more than it needs to"],
      ["tokunseba verify", "Prove the proxy is in the path, with evidence rather than a claim"],
      ["tokunseba apps on", "Route applications you open from the Dock, not only from a shell"],
      ["tokunseba off", "Restore every file it touched, from the backup it made"],
    ],
  },
  {
    group: "Seeing what happened",
    items: [
      ["tokunseba status", "Is it running, and what did it do today"],
      ["tokunseba report", "The whole window on one page, with graphs"],
      ["tokunseba top", "The biggest reductions, and what nothing could be done about"],
      ["tokunseba explain <id>", "One request, original beside replacement, block by block"],
      ["tokunseba expand <handle>", "The full original text behind a handle"],
      ["tokunseba dashboard", "The same view in a browser, served from 127.0.0.1"],
    ],
  },
  {
    group: "Deciding how far it goes",
    items: [
      ["tokunseba tier", "Which tiers are on, and what each one may change"],
      ["tokunseba tier explain 2", "One tier in full, before you turn it on"],
      ["tokunseba replay", "Re-run your own recorded traffic under a setting you have not committed to"],
      ["tokunseba route", "Prompt driven routing rules"],
      ["tokunseba route test \"...\"", "Where this prompt would go, sending nothing anywhere"],
      ["tokunseba advise", "What your prompts looked like, and what routing would move"],
    ],
  },
  {
    group: "Without the proxy",
    items: [
      ["tokunseba run -- pytest -q", "Run a command and print its output already compressed"],
      ["tokunseba wrap claude", "Run one tool through the proxy without changing its config"],
      ["tokunseba wrap-any -- cmd", "The same for anything else"],
      ["tokunseba mcp", "MCP server exposing the expand tool"],
      ["import tokunseba", "compress(), shrink() and expand() from Python"],
    ],
  },
];

const EXTRAS = [
  {
    t: "A local judge, if you want one",
    d: "Routing decisions can be made by a rules engine that ships with it, or by a small model that runs on your machine. The model is opt in, states its memory and disk footprint before it downloads anything, and one command removes it again.",
  },
  {
    t: "A control arm you did not have to build",
    d: "Every session is assigned at random to control or treatment. Both land in the same ledger, and tokunseba stats --ab puts them side by side, so the claim is checkable against your own traffic.",
  },
  {
    t: "Credentials never leave in the clear",
    d: "Requests are scanned for secrets before anything is written to disk, so a detected credential never reaches a stored blob or a stored request body. With tier 3 on, it is redacted before the request leaves at all.",
  },
  {
    t: "Tool results that look like instructions get labelled",
    d: "A page or a file that tells your agent to do something is data, not a command. Suspected prompt injection is marked rather than silently passed on.",
  },
  {
    t: "A status line for your editor",
    d: "tokunseba statusline reads your tool's JSON on stdin and prints one line: whether the proxy is in the path, the context you are carrying, and what has been kept off the wire today.",
  },
  {
    t: "An MCP server for agents without a shell",
    d: "The expand tool is exposed over MCP, so an agent that cannot run commands can still ask for the full text behind any handle.",
  },
  {
    t: "Applications you open from the Dock",
    d: "A GUI application never reads your shell profile, so it never sees the variables your terminal does. tokunseba apps on handles that case explicitly, and says what it is changing before it does.",
  },
  {
    t: "History that expires on your terms",
    d: "Kept for ninety days unless you say otherwise, anywhere from a day to forever, pruned automatically or by hand. tokunseba retention show says how much is actually stored.",
  },
  {
    t: "It fails open, always",
    d: "If tokunseba hits a bug it forwards your request exactly as your tool sent it and records the failure. Optimising a request is never worth failing it.",
  },
];

export default function Home() {
  return (
    <>
      <Nav />
      <main id="top">
        {/* ------------------------------------------------------------- hero */}
        <div className="shell">
          <section className={s.hero}>
            <Backdrop />
            <div className={`${s.heroInner} rise`}>
              <p className={`eyebrow ${s.heroEyebrow}`}>Local proxy, no account, no telemetry</p>
              <h1>
                Your agent sends far more than it needs. <em>tokunseba sends less.</em>
              </h1>
              <p className={s.heroLead}>
                One process on <b>127.0.0.1</b> in front of every AI coding tool on your
                machine. It shrinks each request <b>without losing a byte</b>, keeps the
                prompt cache intact, and can route a turn to the model that turn actually
                needs. Everything it removes stays one command away.
              </p>
              <div className={s.heroCta}>
                <a className="btn btn-primary" href="#install">Install it</a>
                <a className="btn btn-dark" href="#how">See how it works</a>
              </div>
              <p className={s.heroNote}>
                Python 3.12 to 3.14. macOS, Linux and Windows. MIT licensed.
              </p>

              <dl className={s.heroStats}>
                <div>
                  <dt>Measured turn</dt>
                  <dd>98.6%<span>9,629 tokens down to 138</span></dd>
                </div>
                <div>
                  <dt>Recovery</dt>
                  <dd>Byte exact<span>every handle, every time</span></dd>
                </div>
                <div>
                  <dt>Protocols</dt>
                  <dd>4<span>Anthropic, OpenAI, Gemini, Ollama</span></dd>
                </div>
                <div>
                  <dt>Leaves your machine</dt>
                  <dd>Nothing<span>except the call you were making</span></dd>
                </div>
              </dl>
            </div>
          </section>
        </div>

        {/* --------------------------------------------------------- promises */}
        <section className="section shell">
          <div className={s.promises}>
            <Promise
              title="It runs on your machine"
              body="No account, no sign in, no plan, no telemetry. The only outbound traffic is the request your tool was already making, to the provider your tool already chose."
            />
            <Promise
              title="It does not lose anything"
              body="Every removal is content addressed and stored locally. Expand a handle and you get the original back, byte for byte, with the failures and the stack traces still in it."
            />
            <Promise
              title="It measures itself"
              body="Sessions are split at random into a control arm and a treatment arm, both recorded in the same ledger. You can check the claim against your own traffic instead of believing a number."
            />
          </div>
        </section>

        {/* ------------------------------------------------------- the problem */}
        <section className="section shell">
          <div className="panel">
            <p className="eyebrow">The problem</p>
            <h2 style={{ marginTop: 10, maxWidth: "20ch" }}>
              Almost none of your context is your thinking
            </h2>
            <div className={s.feature} style={{ marginTop: 28 }}>
              <div>
                <p className="lead">
                  A coding agent reads a file, runs the tests, lists a directory, reads the
                  file again, and sends all of it back on every single turn. The question you
                  typed is a few hundred tokens. The transcript around it is tens of thousands,
                  and most of it is text the model has already seen or never needed.
                </p>
                <ul className={s.bullets}>
                  <li><b>The same file, five times.</b> Once per turn after it was first read.</li>
                  <li><b>Nine hundred lines of passing tests</b> wrapped around the one that failed.</li>
                  <li><b>Lock files and minified bundles</b> that carry no information a model can use.</li>
                  <li><b>A whole module</b> when the question was about one function in it.</li>
                </ul>
              </div>
              <pre className="code">
{`$ `}<span className="k">tokunseba top</span>{`

where the tokens went          was     now
`}<span className="p">summary:pytest</span>{`              11.7k      55
`}<span className="p">dedup_ref</span>{`                   11.7k      38
`}<span className="p">outline:python</span>{`               23k     3.1k
`}<span className="p">junk:lockfile</span>{`              8.4k      31

`}<span className="c">what could not be helped</span>{`
`}<span className="w">passthrough</span>{`  6.6k  a first read of a short file
`}<span className="w">passthrough</span>{`  4.9k  prose the model has to see`}
              </pre>
            </div>
          </div>
        </section>

        {/* --------------------------------------------------------------- how */}
        <section className="section shell" id="how">
          <p className="eyebrow">How it works</p>
          <h2 style={{ marginTop: 10, maxWidth: "22ch" }}>
            Four tiers. You decide how far it goes.
          </h2>
          <p className="lead" style={{ marginTop: 14 }}>
            Each tier says what it is allowed to change before you turn it on, and every one
            of them can be turned off on its own. Tier 3 is the only tier that can change an
            answer, and it starts off.
          </p>
          <div className={s.pipe}>
            {TIERS.map((t) => (
              <article className={s.tier} key={t.n} data-on={t.state === "off" ? "off" : "on"}>
                <div className={s.tierHead}>
                  <span className={s.tierNum}>tier {t.n}</span>
                  <span className={`pill ${t.state === "off" ? "pill-quiet" : "pill-good"}`}>
                    {t.state}
                  </span>
                </div>
                <h3>{t.name}</h3>
                <p style={{ color: "var(--ink)", fontWeight: 500 }}>{t.may}</p>
                <p>{t.does}</p>
              </article>
            ))}
          </div>

          <div className="grid g3" style={{ marginTop: 16 }}>
            {FEATURES.map((f) => (
              <article className="card" key={f.t}>
                <h3>{f.t}</h3>
                <p>{f.d}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ----------------------------------------------------------- reading */}
        <section className="section shell" id="reading">
          <div className="panel">
            <div className={s.feature}>
              <div>
                <p className="eyebrow">Reading a file</p>
                <h2 style={{ marginTop: 10 }}>Keep the shape, fold the bodies</h2>
                <p className="lead" style={{ marginTop: 14 }}>
                  When an assistant asks to read a long module it almost never needs every
                  line. It needs to know what is in there. tokunseba keeps everything that
                  names something and folds the rest, and the line numbers that survive are
                  the file&rsquo;s own, so the gap says exactly which lines to ask for.
                </p>
                <ul className={s.bullets}>
                  <li><b>Python</b> is parsed with the standard library, so the ranges are exact.</li>
                  <li>
                    <b>JavaScript, TypeScript, Go, Rust, Java, Kotlin, Swift, Scala, C, C++,
                    C#, Objective-C and PHP</b> are scanned by a reader that tracks strings
                    and comments.
                  </li>
                  <li>
                    When the scan is not certain it <b>folds nothing</b>. A file sent whole is
                    merely large. A file folded in the wrong place is wrong.
                  </li>
                  <li>
                    Short files, short bodies, files that do not parse and files that are
                    mostly signatures already are <b>left exactly as they arrived</b>.
                  </li>
                </ul>
              </div>
              <pre className="code">
{`     1  `}<span className="k">import</span>{` { readFile } `}<span className="k">from</span>{` "node:fs/promises";
     2  `}<span className="k">import type</span>{` { Config } `}<span className="k">from</span>{` "./config";
     3
     4  `}<span className="k">export const</span>{` DEFAULT_PORT = 7777;
     5
     6  `}<span className="c">/** Loads a config file and merges the defaults. */</span>{`
     7  `}<span className="k">export async function</span>{` loadConfig(path: string) {
        `}<span className="p">// [tokunseba: 15 lines folded; whole file:</span>{`
        `}<span className="p">//  tokunseba expand h_4b91c07e]</span>{`
    23  }
    24
    25  `}<span className="k">export class</span>{` Proxy {
    26    `}<span className="k">private</span>{` port: number;
    27
    28    constructor(port: number) { `}<span className="k">this</span>{`.port = port; }
    29
    30    `}<span className="k">async</span>{` start(): Promise<void> {
        `}<span className="p">// [tokunseba: 9 lines folded; whole file:</span>{`
        `}<span className="p">//  tokunseba expand h_4b91c07e]</span>{`
    40    }
    41  }`}
              </pre>
            </div>
          </div>
        </section>

        {/* ----------------------------------------------------------- routing */}
        <section className="section shell" id="routing">
          <div className={`${s.feature} ${s.flip}`}>
            <div>
              <p className="eyebrow">Routing</p>
              <h2 style={{ marginTop: 10 }}>
                The right model for the turn, across protocols
              </h2>
              <p className="lead" style={{ marginTop: 14 }}>
                You have a frontier model on a subscription, an API key for something else,
                and something running locally. tokunseba reads the opening prompt of a
                conversation, labels its domain and difficulty, and sends the turn where you
                said turns like that should go.
              </p>
              <ul className={s.bullets}>
                <li>
                  <b>It rewrites the turn, it does not just forward it.</b> An Anthropic shaped
                  request routed to an OpenAI shaped endpoint goes out converted and comes back
                  converted. System prompts, tool definitions, tool calls and their results,
                  images, stop reasons, usage and error envelopes are all mapped.
                </li>
                <li>
                  <b>Streaming survives the translation.</b> A streamed reply is rebuilt event
                  by event rather than buffered, so it still arrives a token at a time.
                </li>
                <li>
                  <b>It abstains rather than guesses.</b> A routing decision only fires when the
                  judge clears a confidence gate. Anything touching finance, law, medicine or
                  security is never routed down.
                </li>
                <li>
                  <b>You can check it first.</b> <code>tokunseba route test</code> shows where a
                  prompt would go and sends nothing anywhere.
                </li>
              </ul>
            </div>
            <pre className="code">
{`$ `}<span className="k">tokunseba models add</span>{` deepseek https://api.deepseek.com
$ `}<span className="k">tokunseba route add</span>{` --max-difficulty 1 \\
      --to deepseek --model deepseek-chat
$ `}<span className="k">tokunseba route add</span>{` --domain devops \\
      --to ollama --model qwen3-coder:30b
$ `}<span className="k">tokunseba route enable</span>{`

$ `}<span className="k">tokunseba route test</span>{` "rename this variable"

  domain      code        `}<span className="c">confidence 0.91</span>{`
  difficulty  trivial     `}<span className="c">confidence 0.84</span>{`
  sensitive   no
  `}<span className="g">would go to deepseek / deepseek-chat</span>{`
  `}<span className="c">rule 1 matched. nothing was sent.</span>
            </pre>
          </div>
        </section>

        {/* ------------------------------------------------------------ replay */}
        <section className="section shell">
          <div className="panel">
            <div className={s.feature}>
              <div>
                <p className="eyebrow">Before you commit to a setting</p>
                <h2 style={{ marginTop: 10 }}>Try it against your own traffic</h2>
                <p className="lead" style={{ marginTop: 14 }}>
                  Every setting comes with the same question, and no documentation can answer
                  it: what would this have done to <em>my</em> work? A number measured on
                  somebody else&rsquo;s repository is not an answer.
                </p>
                <p className="lead" style={{ marginTop: 14 }}>
                  <code>tokunseba replay</code> re-runs traffic that already happened under a
                  configuration you have not committed to, from the request bodies already on
                  disk. Nothing is sent anywhere, and nothing of yours is written: the
                  replay&rsquo;s ledger and blob store live in a temporary directory that is
                  removed when it finishes.
                </p>
              </div>
              <pre className="code">
{`$ `}<span className="k">tokunseba replay</span>{` --since 7d --tier 2

312 requests replayed under tier 2.
                    tokens removed
as it ran                  1.41M
as configured here         2.08M
`}<span className="g">difference                  +674k</span>{`

transform        blocks
`}<span className="p">outline:python</span>{`       46
`}<span className="p">outline:ts</span>{`           18
`}<span className="p">summary:pytest</span>{`       31

84 of 312 requests would come out different.
`}<span className="c">--verbose lists the request ids, so any one
of them can be read with tokunseba explain.</span>
              </pre>
            </div>
          </div>
        </section>

        {/* --------------------------------------------------------- dashboard */}
        <section className="section shell" id="dashboard">
          <div style={{ maxWidth: "46rem" }}>
            <p className="eyebrow">Watching it</p>
            <h2 style={{ marginTop: 10 }}>A dashboard in the terminal, or in a browser</h2>
            <p className="lead" style={{ marginTop: 14 }}>
              <code>tokunseba ui</code> draws the whole thing in your terminal and{" "}
              <code>tokunseba watch</code> keeps it redrawing. Neither needs a browser, a
              port or a window, which matters when the machine you are working on is reached
              over ssh. When you would rather leave it open on a second screen, one command
              serves the same view as a page.
            </p>
          </div>

          <div style={{ marginTop: 26, maxWidth: "34rem" }}>
            <Copy cmd="tokunseba dashboard" />
          </div>

          <div className={s.frame} style={{ marginTop: 24 }}>
            <div className={s.chrome}>
              <i /><i /><i />
              <span>127.0.0.1</span>
            </div>
            <DashboardShot />
          </div>

          <div className="grid g3" style={{ marginTop: 20 }}>
            <article className="card">
              <h3>It binds the loopback address</h3>
              <p>
                The socket is opened on 127.0.0.1 and on a port the operating system hands
                out. Nothing outside this machine can reach it.
              </p>
            </article>
            <article className="card">
              <h3>It checks the name it was asked by</h3>
              <p>
                Every request is compared against the Host header it arrived with, which is
                what stops a page you happened to be visiting from reaching in by pointing a
                hostname at 127.0.0.1. Same origin rules do not cover that case.
              </p>
            </article>
            <article className="card">
              <h3>It fetches nothing from the internet</h3>
              <p>
                One file, no font host, no script CDN, no beacon. Pull the network cable out
                and it still renders. A test asserts this against the bytes on disk rather
                than trusting the comment above them.
              </p>
            </article>
          </div>
        </section>

        {/* ----------------------------------------------------------- compare */}
        <section className="section shell">
          <p className="eyebrow">Why not something else</p>
          <h2 style={{ marginTop: 10, maxWidth: "24ch" }}>
            The other ways to make a context window go further
          </h2>
          <div className="table-wrap" style={{ marginTop: 22 }}>
            <table>
              <thead>
                <tr>
                  <th />
                  <th className="mine">tokunseba</th>
                  <th>Compact by hand</th>
                  <th>A bigger context window</th>
                  <th>A hosted optimiser</th>
                </tr>
              </thead>
              <tbody>
                <Row
                  label="What is removed"
                  mine="Repeats, folded bodies, summarised output"
                  a="Whatever the summariser drops"
                  b="Nothing"
                  c="Repeats and boilerplate"
                />
                <Row
                  label="Getting it back"
                  mine="Byte exact, one command"
                  a="Gone"
                  b="n/a"
                  c="Usually, from their cache"
                />
                <Row
                  label="Where your code goes"
                  mine="Nowhere new"
                  a="Nowhere new"
                  b="Nowhere new"
                  c="Depends on the service"
                />
                <Row
                  label="Effort from you"
                  mine="One command, once"
                  a="Every session"
                  b="One click, recurring"
                  c="Sign up, then once"
                />
                <Row
                  label="Prompt cache"
                  mine="Preserved, and repaired"
                  a="Broken on every compact"
                  b="Unchanged"
                  c="Varies"
                />
                <Row
                  label="Proof it worked"
                  mine="Control arm in your own ledger"
                  a="None"
                  b="n/a"
                  c="Their dashboard"
                />
                <Row
                  label="Chooses the model"
                  mine="Yes, and across protocols"
                  a="No"
                  b="No"
                  c="Rarely"
                />
              </tbody>
            </table>
          </div>
          <p className="small dim" style={{ marginTop: 14, maxWidth: "70ch" }}>
            Savings depend entirely on what you do. Long agentic sessions with heavy tool use
            are where the wins are; short chats save almost nothing. That is why tokunseba
            ships the measurement rather than a promise.
          </p>
        </section>

        {/* -------------------------------------------------------- everything */}
        <section className="section shell">
          <p className="eyebrow">Everything else</p>
          <h2 style={{ marginTop: 10, maxWidth: "22ch" }}>
            The rest of what is in the box
          </h2>
          <div className="grid g3" style={{ marginTop: 26 }}>
            {EXTRAS.map((e) => (
              <article className="card" key={e.t}>
                <h3>{e.t}</h3>
                <p>{e.d}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------- commands */}
        <section className="section shell" id="commands">
          <p className="eyebrow">The command line</p>
          <h2 style={{ marginTop: 10, maxWidth: "22ch" }}>
            Fifty seven commands, and each one says what it will do first
          </h2>
          <p className="lead" style={{ marginTop: 14 }}>
            Nothing changes a file on your machine without telling you what it is about to
            change, and everything it touches is backed up first.
          </p>
          <div className={s.cmdgrid} style={{ marginTop: 26 }}>
            {COMMANDS.map((c) => (
              <div className={s.cmdcard} key={c.group}>
                <h3>{c.group}</h3>
                <dl>
                  {c.items.map(([cmd, what]) => (
                    <div key={cmd}>
                      <dt>{cmd}</dt>
                      <dd>{what}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </section>

        {/* ----------------------------------------------------------- install */}
        <section className="section shell" id="install">
          <div className={s.closing}>
            <Backdrop />
            <div className={s.closingInner}>
              <Mark size={40} />
              <h2>Point your tools at it and keep working</h2>
              <p>
                One command configures every supported tool, backs up every file it touches,
                and starts the proxy in the background. <code>tokunseba off</code> puts it all
                back.
              </p>
              <div style={{ width: "min(30rem, 100%)", display: "grid", gap: 10, marginTop: 6 }}>
                <Copy cmd="uv tool install tokunseba" />
                <Copy cmd="tokunseba init" />
              </div>
              <p className="small" style={{ color: "rgba(255,255,255,.5)" }}>
                Or <code>pipx install tokunseba</code>. Python 3.12 to 3.14, macOS, Linux and
                Windows. Then run <code>tokunseba doctor</code> to see what it found.
              </p>
              <div className={s.heroCta} style={{ marginTop: 2 }}>
                <a className="btn btn-dark" href={REPO} target="_blank" rel="noreferrer noopener">
                  Read the source
                </a>
                <a
                  className="btn btn-dark"
                  href="https://pypi.org/project/tokunseba/"
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  On PyPI
                </a>
              </div>
            </div>
          </div>
        </section>

        <Footer />
      </main>
    </>
  );
}

function Promise({ title, body }: { title: string; body: string }) {
  return (
    <div className={s.promise}>
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.6" opacity=".35" />
        <path
          d="M6 10.2l2.6 2.6L14 7.4"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
    </div>
  );
}

function Row({ label, mine, a, b, c }: Record<"label" | "mine" | "a" | "b" | "c", string>) {
  return (
    <tr>
      <th>{label}</th>
      <td className="mine"><b>{mine}</b></td>
      <td className="dim">{a}</td>
      <td className="dim">{b}</td>
      <td className="dim">{c}</td>
    </tr>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <div className="shell footer-cols">
        <div>
          <Wordmark size={24} />
          <p className="small dim" style={{ marginTop: 10, maxWidth: "34ch" }}>
            One local proxy in front of every AI coding tool on your machine. MIT licensed,
            and it never phones home.
          </p>
        </div>
        <div>
          <h4>Project</h4>
          <ul>
            <li><a href={REPO}>Source</a></li>
            <li><a href={`${REPO}/blob/main/README.md`}>Documentation</a></li>
            <li><a href={`${REPO}/blob/main/CHANGELOG.md`}>Changelog</a></li>
            <li><a href="https://pypi.org/project/tokunseba/">PyPI</a></li>
          </ul>
        </div>
        <div>
          <h4>On this page</h4>
          <ul>
            <li><a href="#how">How it works</a></li>
            <li><a href="#reading">Reading files</a></li>
            <li><a href="#routing">Routing</a></li>
            <li><a href="#dashboard">Dashboard</a></li>
          </ul>
        </div>
        <div>
          <h4>Getting help</h4>
          <ul>
            <li><a href={`${REPO}/issues`}>Report something</a></li>
            <li><a href={`${REPO}/blob/main/CONTRIBUTING.md`}>Contributing</a></li>
            <li><a href={`${REPO}/blob/main/LICENSE`}>Licence</a></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
