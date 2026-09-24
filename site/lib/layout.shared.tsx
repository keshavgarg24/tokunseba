import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { Wordmark } from '@/components/logo';
import { pypiUrl, repoUrl } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: <Wordmark />,
    },
    // Deliberately no long link list. The sidebar already holds every page, and a second
    // navigation that disagrees with the first is worse than no second navigation.
    links: [{ text: 'PyPI', url: pypiUrl, external: true }],
    githubUrl: repoUrl,
  };
}
