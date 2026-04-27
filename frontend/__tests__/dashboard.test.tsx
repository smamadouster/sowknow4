import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import DashboardPage from '../app/[locale]/dashboard/page';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
}));

// Mock next-intl
jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    const dict: Record<string, Record<string, string>> = {
      dashboard: {
        title: 'Dashboard',
        total_documents: 'Total Documents',
        uploads_today: 'Uploads Today',
        indexed_pages: 'Indexed Pages',
        total_articles: 'Total Articles',
        articles_status: 'Articles Status',
        document_distribution: 'Document Distribution',
        articles_breakdown: 'Articles Breakdown',
        uploads_trend: 'Uploads Trend',
        articles_trend: 'Articles Trend',
        public: 'Public',
        confidential: 'Confidential',
      },
      admin: {
        indexed_articles: 'Indexed',
        pending_articles: 'Pending',
        generating_articles: 'Generating',
        error_articles: 'Error',
        anomalies_title: 'Anomalies',
        hours_stuck: '{hours}h stuck',
      },
      common: {
        loading: 'Loading…',
        error: 'Error',
      },
    };
    return (key: string, _params?: Record<string, unknown>) => dict[namespace]?.[key] ?? key;
  },
  useLocale: () => 'en',
}));

// Mock auth store — simulate admin user
jest.mock('@/lib/store', () => ({
  useAuthStore: () => ({
    user: { id: '1', email: 'admin@test.com', full_name: 'Admin', role: 'admin' },
    _hasHydrated: true,
  }),
}));

// Mock API client — simulate all endpoints failing
const mockApiGetStats = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });
const mockApiGetAnomalies = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });
const mockApiGetUploadsHistory = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });
const mockApiGetArticlesHistory = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });
const mockApiGetArticlesStats = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });
const mockApiGetPipelineStats = jest.fn().mockResolvedValue({ status: 403, error: 'Forbidden' });

jest.mock('@/lib/api', () => ({
  api: {
    getStats: () => mockApiGetStats(),
    getAnomalies: () => mockApiGetAnomalies(),
    getUploadsHistory: () => mockApiGetUploadsHistory(),
    getArticlesHistory: () => mockApiGetArticlesHistory(),
    getArticlesStats: () => mockApiGetArticlesStats(),
    getPipelineStats: () => mockApiGetPipelineStats(),
  },
}));

describe('DashboardPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders error state instead of infinite skeletons when APIs fail', async () => {
    render(<DashboardPage />);

    // Wait for loading spinner to disappear
    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument();
    });

    // Error placeholders should be visible instead of pulsing skeletons
    const errorElements = screen.getAllByText('Error');
    expect(errorElements.length).toBeGreaterThan(0);
  });
});
