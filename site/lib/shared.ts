import { createGetUrl } from 'fumadocs-core/source';

export const appName = 'tokunseba';
export const appTagline =
  'One local proxy in front of every AI coding tool on your machine. It shrinks each ' +
  'request without losing a byte, and sends each turn to the model that turn needs.';

export const docsRoute = '/docs';
export const docsImageRoute = '/og/docs';
export const docsContentRoute = '/llms.mdx/docs';

export const gitConfig = {
  user: 'keshavgarg24',
  repo: 'tokunseba',
  branch: 'main',
};

export const repoUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;
export const pypiUrl = 'https://pypi.org/project/tokunseba/';

const getContentUrl = createGetUrl(docsContentRoute);

export function getPageMarkdownUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'content.md'];

  return { segments, url: getContentUrl(segments, page.locale) };
}

const getImageUrl = createGetUrl(docsImageRoute);

export function getPageImageUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'image.png'];

  return { segments, url: getImageUrl(segments, page.locale) };
}
