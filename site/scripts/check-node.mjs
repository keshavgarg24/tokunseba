// Fumadocs' MDX loader is an ES module, and Next loads it with require(). Node only allows
// that from 20.19.0 and 22.12.0 onward. Below those, the failure is a wall of
// "require() of ES Module ... not supported" pointing at a file inside node_modules, which
// says nothing about what to do. This says it instead.
const [major, minor] = process.versions.node.split('.').map(Number);
const ok = (major === 20 && minor >= 19) || (major === 21 && minor >= 99) || major >= 22;

if (!ok) {
  const line = '='.repeat(72);
  console.error(`\n${line}
  This site needs Node 20.19 or newer. You are on ${process.versions.node}.

  Node only allows require() of an ES module from 20.19.0 and 22.12.0 onward, and
  Fumadocs' MDX loader is an ES module that Next loads that way. On an older Node
  the build fails inside node_modules with a message that explains nothing.

  With nvm:        nvm install 22 && nvm use 22
  With Homebrew:   brew install node@22
  Or download:     https://nodejs.org

  There is an .nvmrc here, so \`nvm use\` in this directory picks the right one.
${line}\n`);
  process.exit(1);
}
