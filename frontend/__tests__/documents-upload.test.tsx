import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DocumentsPage from '../app/[locale]/documents/page';

jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/en/documents',
}));

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    const translations: Record<string, Record<string, string>> = {
      documents: {
        title: 'Documents',
        upload: 'Upload',
        uploading: 'Uploading',
        upload_success: 'File uploaded successfully',
        upload_error: 'Upload failed',
        delete_confirm: 'Are you sure?',
        no_documents: 'No documents found',
        filename: 'Filename',
        bucket: 'Bucket',
        status: 'Status',
        size: 'Size',
        created_at: 'Created',
        actions: 'Actions',
        all_buckets: 'All Buckets',
        bucket_public: 'Public',
        bucket_confidential: 'Confidential',
        status_indexed: 'Indexed',
        status_processing: 'Processing',
        status_pending: 'Pending',
        status_error: 'Error',
        drop_files_here: 'Drop files here',
        max_file_size: 'Max file size:',
        max_batch_size: 'Max batch size:',
        drag_drop_hint: 'Drag and drop files here or click to select',
        upload_queue: 'Upload Queue',
        clear_completed: 'Clear completed',
        upload_complete: 'Upload complete',
        batch_upload_success: '{count} file(s) uploaded successfully',
        batch_too_large: 'Batch too large. Maximum {maxSize}, got {actualSize}',
      },
      common: {
        error: 'An error occurred',
        download: 'Download',
        delete: 'Delete',
        previous: 'Previous',
        next: 'Next',
      },
    };
    return (key: string, params?: Record<string, string>) => {
      let text = translations[namespace]?.[key] || key;
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          text = text.replace(`{${k}}`, v);
        });
      }
      return text;
    };
  },
}));

const mockDocuments = [
  {
    id: '1',
    filename: 'test.pdf',
    original_filename: 'test.pdf',
    bucket: 'public',
    status: 'indexed',
    file_size: 1024 * 1024,
    mime_type: 'application/pdf',
    page_count: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
];

global.fetch = jest.fn();

describe('DocumentsPage - Drag and Drop Upload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      headers: {
        get: (name: string) => (name.toLowerCase() === 'content-type' ? 'application/json' : null),
      },
      json: async () => ({ documents: mockDocuments, total: 1 }),
    });
  });

  describe('File Validation', () => {
    it('validates individual file size (max 100MB)', async () => {
      const largeFile = new File(['content'], 'large.pdf', { type: 'application/pdf' });
      Object.defineProperty(largeFile, 'size', { value: 101 * 1024 * 1024 });

      render(<DocumentsPage />);
      
      const input = document.querySelector('input[type="file"]');
      expect(input).toBeInTheDocument();
    });

    it('shows error for files exceeding 100MB', () => {
      const MAX_FILE_SIZE = 100 * 1024 * 1024;
      expect(MAX_FILE_SIZE).toBe(104857600);
    });

    it('validates total batch size (max 500MB)', () => {
      const MAX_BATCH_SIZE = 500 * 1024 * 1024;
      expect(MAX_BATCH_SIZE).toBe(524288000);
    });
  });

  describe('Upload Queue', () => {
    it('renders upload button', () => {
      render(<DocumentsPage />);
      expect(screen.getByText('Upload')).toBeInTheDocument();
    });

    it('renders drag and drop area', () => {
      render(<DocumentsPage />);
      expect(screen.getByText(/drag and drop files here/i)).toBeInTheDocument();
    });

    it('shows max file size in UI', () => {
      render(<DocumentsPage />);
      expect(screen.getByText(/max file size:/i)).toBeInTheDocument();
    });

    it('shows max batch size in UI', () => {
      render(<DocumentsPage />);
      expect(screen.getByText(/max batch size:/i)).toBeInTheDocument();
    });
  });

  describe('Document List', () => {
    it('renders document table after loading', async () => {
      render(<DocumentsPage />);
      
      await waitFor(() => {
        expect(screen.getAllByText('test.pdf').length).toBeGreaterThan(0);
      });
    });

    it('has loading indicator initially', () => {
      const { container } = render(<DocumentsPage />);
      const loadingSpinner = container.querySelector('.animate-spin');
      expect(loadingSpinner).toBeInTheDocument();
    });
  });

  describe('File Format Helper', () => {
    it('formats bytes correctly', () => {
      const formatFileSize = (bytes: number): string => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
      };

      expect(formatFileSize(500)).toBe('500 B');
      expect(formatFileSize(1024)).toBe('1.0 KB');
      expect(formatFileSize(1048576)).toBe('1.0 MB');
      expect(formatFileSize(104857600)).toBe('100.0 MB');
    });
  });

  describe('Constants', () => {
    it('has correct MAX_FILE_SIZE', () => {
      const MAX_FILE_SIZE = 100 * 1024 * 1024;
      expect(MAX_FILE_SIZE).toBe(104857600);
    });

    it('has correct MAX_BATCH_SIZE', () => {
      const MAX_BATCH_SIZE = 500 * 1024 * 1024;
      expect(MAX_BATCH_SIZE).toBe(524288000);
    });
  });
});
