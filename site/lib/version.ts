import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The version of the package this site documents, read at build time from the source of
 * truth rather than typed here. A number written into a page by hand is a number that is
 * wrong from the next release onward, and nothing tells you.
 *
 * Returns an empty string when the site is built outside the repository, in which case
 * whatever displays it should simply not display it.
 */
export function packageVersion(): string {
  for (const candidate of ['../pyproject.toml', 'pyproject.toml']) {
    try {
      const toml = readFileSync(join(process.cwd(), candidate), 'utf8');
      const found = toml.match(/^version\s*=\s*"([^"]+)"/m);
      if (found) return found[1];
    } catch {
      // try the next one
    }
  }
  return '';
}
