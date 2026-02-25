'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useDropzone, FileRejection } from 'react-dropzone';
import { useTranslations } from 'next-intl';
import { useAuthStore, canAccessConfidential } from '@/lib/store';

interface Document {
  id: string;
  filename: string;
  original_filename: string;
  bucket: string;
  status: string;
  file_size: number;
  mime_type: string;
  page_count: number;
  created_at: string;
  updated_at: string;
}

interface FileUploadItem {
  file: File;
  id: string;
  status: 'pending' | 'uploading' | 'success' | 'error' | 'rejected';
  progress: number;
  error?: string;
}

const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB per file
const MAX_BATCH_SIZE = 500 * 1024 * 1024; // 500MB total batch

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function DocumentsPage() {
  const t = useTranslations('documents');
  const tCommon = useTranslations('common');
  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';
  const canAccessConf = canAccessConfidential(user);

  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const uploadingCount = useRef(0);
  const [uploading, setUploading] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [bucketFilter, setBucketFilter] = useState<'all' | 'public' | 'confidential'>('all');
  // R8 — search state
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  // R7 — sort state
  const [sortBy, setSortBy] = useState<'created_at' | 'original_filename' | 'file_size' | 'status'>('created_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  // Batch upload state
  const [fileQueue, setFileQueue] = useState<FileUploadItem[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);

  const pageSize = 50;

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Primary load effect — reruns when page, bucket, search, or sort changes
  useEffect(() => {
    loadDocuments();
  }, [page, bucketFilter, debouncedSearch, sortBy, sortDir]);

  // R8 — debounce: reset to page 1, then commit search after 400 ms
  useEffect(() => {
    setPage(1);
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 400);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // R9 — real-time polling: refresh every 5 s while any doc is pending/processing
  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.status === 'pending' || d.status === 'processing',
    );
    if (!hasProcessing) return;

    const interval = setInterval(() => {
      loadDocuments();
    }, 5000);

    return () => clearInterval(interval);
  }, [documents]);

  // R7 — sort handler
  const handleSort = (col: typeof sortBy) => {
    if (sortBy === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortDir('desc');
    }
    setPage(1);
  };

  const getToken = (): string | null => {
    if (typeof window === 'undefined') return null;
    const match = document.cookie.match(/access_token=([^;]+)/);
    return match ? match[1] : null;
  };

  // Generate unique ID for file items
  const generateId = () => Math.random().toString(36).substring(2, 15);

  // Dropzone configuration
  const onDrop = useCallback(
    (acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
      const currentTime = Date.now();

      // Add rejected files with error status
      const rejectedItems: FileUploadItem[] = rejectedFiles.map((rejection) => ({
        file: rejection.file,
        id: generateId(),
        status: 'rejected',
        progress: 0,
        error: rejection.errors[0]?.message || 'File rejected',
      }));

      // Validate batch size for accepted files
      const totalSize = acceptedFiles.reduce((sum, file) => sum + file.size, 0);
      const acceptedItems: FileUploadItem[] = acceptedFiles.map((file) => ({
        file,
        id: generateId(),
        status: 'pending' as const,
        progress: 0,
      }));

      // Check if total batch exceeds 500MB
      let batchError: string | undefined;
      if (totalSize > MAX_BATCH_SIZE) {
        batchError = t('batch_too_large', {
          maxSize: formatFileSize(MAX_BATCH_SIZE),
          actualSize: formatFileSize(totalSize),
        });
        acceptedItems.forEach((item) => {
          item.status = 'rejected';
          item.error = batchError;
        });
      }

      // Combine rejected and accepted, then sort so errors appear first
      const newItems = [...rejectedItems, ...acceptedItems].sort((a, b) => {
        if (a.status === 'rejected' && b.status !== 'rejected') return -1;
        if (a.status !== 'rejected' && b.status === 'rejected') return 1;
        return 0;
      });

      setFileQueue((prev) => [...prev, ...newItems]);

      // Auto-start upload if there are pending files — use setTimeout so setFileQueue
      // above has committed before we read the queue, avoiding the stale closure bug.
      const pendingFiles = newItems.filter((item) => item.status === 'pending');
      if (pendingFiles.length > 0) {
        setTimeout(() => {
          setFileQueue((prev) => {
            const pending = prev.filter((item) => item.status === 'pending');
            if (pending.length > 0 && uploadingCount.current === 0) {
              uploadBatch(pending);
            }
            return prev;
          });
        }, 0);
      }
    },
    [t],
  );

  const { getRootProps, getInputProps, isDragActive: dropzoneIsDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.ms-powerpoint': ['.ppt'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
      'application/vnd.ms-excel': ['.xls'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'application/json': ['.json'],
      'image/png': ['.png'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/gif': ['.gif'],
      'image/bmp': ['.bmp'],
      'image/heic': ['.heic'],
      'video/mp4': ['.mp4'],
      'video/x-msvideo': ['.avi'],
      'video/quicktime': ['.mov'],
      'video/x-matroska': ['.mkv'],
      'application/epub+zip': ['.epub'],
    },
    maxSize: MAX_FILE_SIZE,
    multiple: true,
    disabled: uploading,
  });

  // Update drag active state
  useEffect(() => {
    setIsDragActive(dropzoneIsDragActive);
  }, [dropzoneIsDragActive]);

  // Upload a single file
  const uploadFile = async (
    item: FileUploadItem,
    bucket: string,
  ): Promise<{ success: boolean; error?: string }> => {
    return new Promise((resolve) => {
      const token = getToken();
      const formData = new FormData();
      formData.append('file', item.file);
      formData.append('bucket', bucket);

      const xhr = new XMLHttpRequest();

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const progress = Math.round((event.loaded / event.total) * 100);
          setFileQueue((prev) =>
            prev.map((f) => (f.id === item.id ? { ...f, progress } : f)),
          );
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setFileQueue((prev) =>
            prev.map((f) =>
              f.id === item.id ? { ...f, status: 'success', progress: 100 } : f,
            ),
          );
          resolve({ success: true });
        } else {
          const errorMsg = `Upload failed: ${xhr.status}`;
          setFileQueue((prev) =>
            prev.map((f) =>
              f.id === item.id ? { ...f, status: 'error', error: errorMsg } : f,
            ),
          );
          resolve({ success: false, error: errorMsg });
        }
      };

      xhr.onerror = () => {
        const errorMsg = 'Network error';
        setFileQueue((prev) =>
          prev.map((f) =>
            f.id === item.id ? { ...f, status: 'error', error: errorMsg } : f,
          ),
        );
        resolve({ success: false, error: errorMsg });
      };

      xhr.open('POST', `${API_BASE}/v1/documents/upload`);
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }
      xhr.withCredentials = true;
      xhr.send(formData);
    });
  };

  // Upload batch of files
  const uploadBatch = async (items: FileUploadItem[]) => {
    if (items.length === 0) return;

    uploadingCount.current++;
    setUploading(true);
    const bucket = bucketFilter === 'all' ? 'public' : bucketFilter;

    for (const item of items) {
      // Update status to uploading
      setFileQueue((prev) =>
        prev.map((f) => (f.id === item.id ? { ...f, status: 'uploading' } : f)),
      );

      await uploadFile(item, bucket);
    }

    // Refresh document list after all uploads
    await loadDocuments();

    // Show success message for successful uploads
    const successful = fileQueue.filter((f) => f.status === 'success').length;
    if (successful > 0) {
      setSuccess(t('batch_upload_success', { count: successful }));
      setTimeout(() => setSuccess(null), 5000);
    }

    // Clear completed/failed files from queue after a delay
    setTimeout(() => {
      setFileQueue((prev) =>
        prev.filter((f) => f.status === 'uploading' || f.status === 'pending'),
      );
    }, 3000);

    uploadingCount.current--;
    if (uploadingCount.current === 0) setUploading(false);
  };

  // Remove file from queue
  const removeFromQueue = (id: string) => {
    setFileQueue((prev) => prev.filter((f) => f.id !== id));
  };

  // Clear all completed/failed files
  const clearQueue = () => {
    setFileQueue((prev) =>
      prev.filter((f) => f.status === 'uploading' || f.status === 'pending'),
    );
  };

  const loadDocuments = async () => {
    setLoading(true);
    setError(null);

    try {
      const token = getToken();
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      });
      if (bucketFilter !== 'all') {
        params.append('bucket', bucketFilter);
      }
      // R8 — search param
      if (debouncedSearch) {
        params.append('search', debouncedSearch);
      }
      // R7 — sort params
      params.append('sort_by', sortBy);
      params.append('sort_dir', sortDir);

      const res = await fetch(`${API_BASE}/v1/documents?${params}`, {
        credentials: 'include',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
        setTotal(data.total || 0);
      } else {
        setError(tCommon('error'));
      }
    } catch (e) {
      console.error('Error loading documents:', e);
      setError(tCommon('error'));
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (docId: string, filename: string) => {
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/v1/documents/${docId}/download`, {
        credentials: 'include',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) {
        setError(tCommon('error'));
        return;
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Download error:', e);
      setError(tCommon('error'));
    }
  };

  const handleDelete = async (docId: string) => {
    if (!confirm(t('delete_confirm'))) return;

    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/v1/documents/${docId}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      });

      if (res.ok) {
        loadDocuments();
      }
    } catch (e) {
      console.error('Delete error:', e);
    }
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'indexed':
        return 'bg-green-100 text-green-700';
      case 'processing':
        return 'bg-yellow-100 text-yellow-700';
      case 'pending':
        return 'bg-gray-100 text-gray-700';
      case 'error':
        return 'bg-red-100 text-red-700';
      default:
        return 'bg-gray-100 text-gray-700';
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('title')}</h1>

        {/* R8 — Debounced search input */}
        <div className="flex-1 max-w-sm mx-4">
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('search_placeholder')}
              className="w-full pl-9 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <select
            value={bucketFilter}
            onChange={(e) => setBucketFilter(e.target.value as any)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('all_buckets')}</option>
            <option value="public">{t('bucket_public')}</option>
            {canAccessConf && (
              <option value="confidential">{t('bucket_confidential')}</option>
            )}
          </select>

          {/* Dropzone area */}
          <div {...getRootProps()} className="cursor-pointer">
            <input {...getInputProps()} />
            <button
              disabled={uploading}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
                />
              </svg>
              {uploading ? t('uploading') : t('upload')}
            </button>
          </div>
        </div>
      </div>

      {/* Drag active overlay */}
      {isDragActive && (
        <div className="fixed inset-0 bg-blue-500/20 backdrop-blur-sm z-40 flex items-center justify-center">
          <div className="bg-white rounded-xl shadow-2xl p-8 text-center">
            <svg
              className="w-16 h-16 text-blue-600 mx-auto mb-4 animate-bounce"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <p className="text-lg font-medium text-gray-900">{t('drop_files_here')}</p>
            <p className="text-sm text-gray-500 mt-1">
              {t('max_file_size', { size: formatFileSize(MAX_FILE_SIZE) })}
            </p>
          </div>
        </div>
      )}

      {/* Error messages */}
      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-3 rounded-lg mb-6 flex items-center gap-2">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          {error}
        </div>
      )}

      {/* Success messages */}
      {success && (
        <div className="bg-green-50 text-green-600 px-4 py-3 rounded-lg mb-6 flex items-center gap-2">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          {success}
        </div>
      )}

      {/* File queue with per-file progress bars */}
      {fileQueue.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden mb-6">
          <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="font-medium text-gray-900">
              {t('upload_queue', { count: fileQueue.length })}
            </h3>
            <button onClick={clearQueue} className="text-sm text-gray-500 hover:text-gray-700">
              {t('clear_completed')}
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {fileQueue.map((item) => (
              <div key={item.id} className="px-4 py-3 border-b border-gray-100 last:border-b-0">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    {/* Status icon */}
                    {item.status === 'pending' && (
                      <svg
                        className="w-5 h-5 text-gray-400 flex-shrink-0"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                        />
                      </svg>
                    )}
                    {item.status === 'uploading' && (
                      <div className="w-5 h-5 flex-shrink-0">
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                      </div>
                    )}
                    {item.status === 'success' && (
                      <svg
                        className="w-5 h-5 text-green-500 flex-shrink-0"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                        />
                      </svg>
                    )}
                    {item.status === 'error' && (
                      <svg
                        className="w-5 h-5 text-red-500 flex-shrink-0"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                        />
                      </svg>
                    )}
                    {item.status === 'rejected' && (
                      <svg
                        className="w-5 h-5 text-orange-500 flex-shrink-0"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                        />
                      </svg>
                    )}

                    {/* File info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{item.file.name}</p>
                      <p className="text-xs text-gray-500">
                        {formatFileSize(item.file.size)}
                        {item.error && <span className="text-red-500 ml-2">{item.error}</span>}
                      </p>
                    </div>
                  </div>

                  {/* Remove button */}
                  <button
                    onClick={() => removeFromQueue(item.id)}
                    className="p-1 text-gray-400 hover:text-gray-600 ml-2"
                    disabled={item.status === 'uploading'}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </div>

                {/* Progress bar */}
                {(item.status === 'uploading' || item.status === 'pending') && (
                  <div className="w-full bg-gray-200 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full transition-all duration-300 ${
                        item.status === 'pending' ? 'bg-gray-400' : 'bg-blue-600'
                      }`}
                      style={{ width: item.status === 'pending' ? '0%' : `${item.progress}%` }}
                    ></div>
                  </div>
                )}

                {/* Success/Error/Rejected state */}
                {item.status === 'success' && (
                  <div className="text-xs text-green-600">{t('upload_complete')}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dropzone area - alternative drag target */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-8 mb-6 text-center transition-colors cursor-pointer ${
          isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <input {...getInputProps()} />
        <svg
          className="w-12 h-12 text-gray-400 mx-auto mb-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>
        <p className="text-gray-600 mb-2">
          {isDragActive ? t('drop_files_here') : t('drag_drop_hint')}
        </p>
        <p className="text-sm text-gray-500">
          {t('max_file_size', { size: formatFileSize(MAX_FILE_SIZE) })} •{' '}
          {t('max_batch_size', { size: formatFileSize(MAX_BATCH_SIZE) })}
        </p>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center py-12">
            <svg
              className="w-16 h-16 text-gray-300 mx-auto mb-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-gray-600">{t('no_documents')}</p>
          </div>
        ) : (
          <>
            {/* Mobile card list */}
            <div className="block md:hidden divide-y divide-gray-100">
              {documents.map((doc) => (
                <div key={doc.id} className="px-4 py-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate text-sm">
                        {doc.original_filename || doc.filename}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">{doc.mime_type}</p>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium flex-shrink-0 ${
                        doc.bucket === 'confidential'
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-green-100 text-green-700'
                      }`}
                    >
                      {doc.bucket === 'confidential' ? t('bucket_confidential') : t('bucket_public')}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                    <span className={`px-1.5 py-0.5 rounded font-medium ${getStatusColor(doc.status)}`}>
                      {t(`status_${doc.status}`)}
                    </span>
                    <span>{formatFileSize(doc.file_size)}</span>
                    {doc.page_count && <span>{doc.page_count}p</span>}
                    <span>{formatDate(doc.created_at)}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => handleDownload(doc.id, doc.original_filename || doc.filename)}
                      className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                    >
                      <svg
                        className="w-3.5 h-3.5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                        />
                      </svg>
                      {tCommon('download')}
                    </button>
                    {isAdmin && (
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="flex items-center gap-1 text-xs text-red-600 hover:text-red-800"
                      >
                        <svg
                          className="w-3.5 h-3.5"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                        {tCommon('delete')}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="hidden md:block">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    {/* R7 — sortable headers */}
                    <th
                      className="text-left py-3 px-6 text-sm font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                      onClick={() => handleSort('original_filename')}
                    >
                      <span className="flex items-center gap-1">
                        {t('filename')}
                        {sortBy === 'original_filename' && (
                          <span>{sortDir === 'asc' ? '↑' : '↓'}</span>
                        )}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">
                      {t('bucket')}
                    </th>
                    <th
                      className="text-left py-3 px-4 text-sm font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                      onClick={() => handleSort('status')}
                    >
                      <span className="flex items-center gap-1">
                        {t('status')}
                        {sortBy === 'status' && <span>{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th
                      className="text-left py-3 px-4 text-sm font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                      onClick={() => handleSort('file_size')}
                    >
                      <span className="flex items-center gap-1">
                        {t('size')}
                        {sortBy === 'file_size' && <span>{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500 hidden sm:table-cell">
                      {t('page_count')}
                    </th>
                    <th
                      className="text-left py-3 px-4 text-sm font-medium text-gray-500 cursor-pointer hover:text-gray-700 select-none"
                      onClick={() => handleSort('created_at')}
                    >
                      <span className="flex items-center gap-1">
                        {t('created_at')}
                        {sortBy === 'created_at' && <span>{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">
                      {t('actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-6">
                        <div className="font-medium text-gray-900">
                          {doc.original_filename || doc.filename}
                        </div>
                        <div className="text-xs text-gray-400">{doc.mime_type}</div>
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${
                            doc.bucket === 'confidential'
                              ? 'bg-orange-100 text-orange-700'
                              : 'bg-green-100 text-green-700'
                          }`}
                        >
                          {doc.bucket === 'confidential'
                            ? t('bucket_confidential')
                            : t('bucket_public')}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${getStatusColor(doc.status)}`}
                        >
                          {t(`status_${doc.status}`)}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">
                        {formatFileSize(doc.file_size)}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600 hidden sm:table-cell">
                        {doc.page_count || '—'}
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-600">
                        {formatDate(doc.created_at)}
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() =>
                              handleDownload(doc.id, doc.original_filename || doc.filename)
                            }
                            className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                            title={tCommon('download')}
                          >
                            <svg
                              className="w-4 h-4"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                              />
                            </svg>
                          </button>
                          {isAdmin && (
                            <button
                              onClick={() => handleDelete(doc.id)}
                              className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                              title={tCommon('delete')}
                            >
                              <svg
                                className="w-4 h-4"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {totalPages > 1 && (
                <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
                  <p className="text-sm text-gray-500">
                    Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, total)} of{' '}
                    {total}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {tCommon('previous')}
                    </button>
                    <span className="px-3 py-1.5 text-sm text-gray-600">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {tCommon('next')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
