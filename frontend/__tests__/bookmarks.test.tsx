import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import BookmarksPage from '../app/[locale]/bookmarks/page';
import { parseDomain } from '../app/[locale]/bookmarks/utils';

// Minimal mocks required by the page
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/en/bookmarks',
}));

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    const t: Record<string, Record<string, string>> = {
      bookmarks: {
        title: 'Bookmarks',
        add: 'Add',
        search_placeholder: 'Search bookmarks…',
        empty: 'No bookmarks yet',
        delete_confirm: 'Delete this bookmark?',
        url_placeholder: 'https://',
        title_label: 'Title',
        description_label: 'Description',
        tags_label: 'Tags',
      },
      common: { cancel: 'Cancel', save: 'Save', loading: 'Loading…', delete: 'Delete', edit: 'Edit', close: 'Close' },
    };
    return (key: string) => t[namespace]?.[key] ?? key;
  },
  useLocale: () => 'en',
}));

jest.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => false }));
jest.mock('@/lib/api', () => ({ api: { getBookmarks: jest.fn().mockResolvedValue({ data: { bookmarks: [], total: 0, page: 1, page_size: 50 }, error: null }) } }));


describe('parseDomain', () => {
  it('strips www prefix', () => {
    expect(parseDomain('https://www.github.com/foo')).toBe('github.com');
  });
  it('keeps non-www domains as-is', () => {
    expect(parseDomain('https://towardsdatascience.com/article')).toBe('towardsdatascience.com');
  });
  it('falls back to raw url on invalid input', () => {
    expect(parseDomain('not-a-url')).toBe('not-a-url');
  });
});

describe('BookmarksPage', () => {
  it('renders the page title', async () => {
    render(<BookmarksPage />);
    expect(await screen.findByText('Bookmarks')).toBeInTheDocument();
  });

  it('shows empty state when no bookmarks', async () => {
    render(<BookmarksPage />);
    expect(await screen.findByText('No bookmarks yet')).toBeInTheDocument();
  });

  it('shows Add button on desktop', async () => {
    render(<BookmarksPage />);
    // Desktop: header Add button must be present (FAB is mobile-only)
    expect(await screen.findByRole('button', { name: 'Add' })).toBeInTheDocument();
  });
});
