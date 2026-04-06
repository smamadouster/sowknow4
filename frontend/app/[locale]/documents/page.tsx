'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useDropzone, FileRejection } from 'react-dropzone';
import { useTranslations } from 'next-intl';
import { useAuthStore, useUploadStore, canAccessConfidential } from '@/lib/store';
import api, { getCsrfToken } from '@/lib/api';
import { formatDate } from '@/lib/formatDate';
import { useIsMobile } from '@/hooks/useIsMobile';
import FAB from '@/components/mobile/FAB';
import MobileBottomSheet from '@/components/mobile/MobileBottomSheet';
import PullToRefresh from '@/components/mobile/PullToRefresh';

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

const MAX_FILE_SIZE = 100 * 1024 * 1024;
const MAX_BATCH_SIZE = 500 * 1024 * 1024;

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function DocumentsPage() {
  const t = useTranslations('documents');
  const tCommon = useTranslations('common');
  const { user } = useAuthStore();
  const { setIsUploading } = useUploadStore();
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
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sortBy, setSortBy] = useState<'created_at' | 'original_filename' | 'file_size' | 'status'>('created_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const [fileQueue, setFileQueue] = useState<FileUploadItem[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);
  const [uploadBucket, setUploadBucket] = useState<'public' | 'confidential'>('public');
  const isMobile = useIsMobile();
  const [showFilterSheet, setShowFilterSheet] = useState(false);

  const pageSize = 50;

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  useEffect(() => {
    loadDocuments();
  }, [page, bucketFilter, debouncedSearch, sortBy, sortDir]);

  useEffect(() => {
    setPage(1);
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 400);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const loadDocuments = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.getDocuments(
        page,
        pageSize,
        bucketFilter !== 'all' ? bucketFilter : undefined,
        debouncedSearch || undefined,
        sortBy,
        sortDir
      );

      if (response.status === 200 && response.data) {
        setDocuments(response.data.documents || []);
        setTotal(response.data.total || 0);
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

  const refreshDocuments = useCallback(async () => {
    try {
      const response = await api.getDocuments(
        page,
        pageSize,
        bucketFilter !== 'all' ? bucketFilter : undefined,
        debouncedSearch || undefined,
        sortBy,
        sortDir
      );

      if (response.status === 200 && response.data) {
        setDocuments(response.data.documents || []);
        setTotal(response.data.total || 0);
      }
    } catch (e) {
      console.error('Error refreshing documents:', e);
    }
  }, [page, pageSize, bucketFilter, debouncedSearch, sortBy, sortDir]);

  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.status === 'pending' || d.status === 'processing',
    );
    if (!hasProcessing) return;

    const interval = setInterval(() => {
      refreshDocuments();
    }, 5000);

    return () => clearInterval(interval);
  }, [documents, refreshDocuments]);

  const handleSort = (col: typeof sortBy) => {
    if (sortBy === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortDir('desc');
    }
    setPage(1);
  };

  const generateId = () => Math.random().toString(36).substring(2, 15);

  const onDrop = useCallback(
    (acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
      const rejectedItems: FileUploadItem[] = rejectedFiles.map((rejection) => ({
        file: rejection.file,
        id: generateId(),
        status: 'rejected',
        progress: 0,
        error: rejection.errors[0]?.message || 'File rejected',
      }));

      const totalSize = acceptedFiles.reduce((sum, file) => sum + file.size, 0);
      const acceptedItems: FileUploadItem[] = acceptedFiles.map((file) => ({
        file,
        id: generateId(),
        status: 'pending' as const,
        progress: 0,
      }));

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

      const newItems = [...rejectedItems, ...acceptedItems].sort((a, b) => {
        if (a.status === 'rejected' && b.status !== 'rejected') return -1;
        if (a.status !== 'rejected' && b.status === 'rejected') return 1;
        return 0;
      });

      setFileQueue((prev) => [...prev, ...newItems]);

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

  const dropzoneInputRef = useRef<HTMLInputElement | null>(null);

  const { getRootProps, getInputProps, isDragActive: dropzoneIsDragActive, open: openDropzone } = useDropzone({
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
      'audio/mpeg': ['.mp3'],
      'audio/wav': ['.wav'],
      'audio/ogg': ['.ogg'],
      'audio/flac': ['.flac'],
      'audio/aac': ['.aac'],
      'audio/x-ms-wma': ['.wma'],
      'audio/mp4': ['.m4a'],
      'application/epub+zip': ['.epub'],
      'text/csv': ['.csv'],
      'text/xml': ['.xml'],
      'application/xml': ['.xml'],
    },
    maxSize: MAX_FILE_SIZE,
    multiple: true,
    disabled: uploading,
  });

  useEffect(() => {
    setIsDragActive(dropzoneIsDragActive);
  }, [dropzoneIsDragActive]);

  const uploadFile = async (
    item: FileUploadItem,
    bucket: string,
  ): Promise<{ success: boolean; error?: string }> => {
    return new Promise((resolve) => {
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
      xhr.setRequestHeader('X-CSRF-Token', getCsrfToken());
      xhr.withCredentials = true;
      xhr.send(formData);
    });
  };

  const uploadBatch = async (items: FileUploadItem[]) => {
    if (items.length === 0) return;

    uploadingCount.current++;
    setUploading(true);
    setIsUploading(true);
    const bucket = uploadBucket;

    for (const item of items) {
      setFileQueue((prev) =>
        prev.map((f) => (f.id === item.id ? { ...f, status: 'uploading' } : f)),
      );

      await uploadFile(item, bucket);
    }

    await loadDocuments();

    const successful = fileQueue.filter((f) => f.status === 'success').length;
    if (successful > 0) {
      setSuccess(t('batch_upload_success', { count: successful }));
      setTimeout(() => setSuccess(null), 5000);
    }

    setTimeout(() => {
      setFileQueue((prev) =>
        prev.filter((f) => f.status === 'uploading' || f.status === 'pending'),
      );
    }, 3000);

    uploadingCount.current--;
    if (uploadingCount.current === 0) {
      setUploading(false);
      setIsUploading(false);
    }
  };

  const removeFromQueue = (id: string) => {
    setFileQueue((prev) => prev.filter((f) => f.id !== id));
  };

  const clearQueue = () => {
    setFileQueue((prev) =>
      prev.filter((f) => f.status === 'uploading' || f.status === 'pending'),
    );
  };

  const handleDownload = async (docId: string, filename: string) => {
    try {
      const res = await fetch(`${API_BASE}/v1/documents/${docId}/download`, {
        credentials: 'include',
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
      const response = await api.deleteDocument(docId);

      if (response.status === 200) {
        loadDocuments();
      }
    } catch (e) {
      console.error('Delete error:', e);
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'indexed':
        return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
      case 'processing':
        return 'bg-amber-500/10 text-amber-400 border border-amber-500/20';
      case 'pending':
        return 'bg-vault-700/50 text-text-muted border border-white/[0.06]';
      case 'error':
        return 'bg-red-500/10 text-red-400 border border-red-500/20';
      default:
        return 'bg-vault-700/50 text-text-muted border border-white/[0.06]';
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto pb-24 md:pb-8">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-text-primary font-display">{t('title')}</h1>
          <p className="text-sm text-text-muted mt-1">{total} document{total !== 1 ? 's' : ''}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          {/* Search input */}
          <div className="relative flex-1 sm:flex-initial sm:min-w-[200px]">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted/50"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('search_placeholder')}
              className="w-full pl-9 pr-4 py-2 bg-vault-800/50 border border-white/[0.08] rounded-xl text-sm text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
            />
          </div>

          {/* Bucket filter — hidden on mobile (use filter bottom sheet instead) */}
          <select
            value={bucketFilter}
            onChange={(e) => setBucketFilter(e.target.value as 'all' | 'public' | 'confidential')}
            className="hidden md:block px-3 py-2 bg-vault-800/50 border border-white/[0.08] rounded-xl text-sm text-text-secondary focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all appearance-none cursor-pointer"
          >
            <option value="all">{t('all_buckets')}</option>
            <option value="public">{t('bucket_public')}</option>
            {canAccessConf && (
              <option value="confidential">{t('bucket_confidential')}</option>
            )}
          </select>

          {/* Mobile filter button */}
          <button
            onClick={() => setShowFilterSheet(true)}
            className="p-2 rounded-lg bg-vault-800 border border-white/[0.06] text-text-muted hover:text-amber-400 min-w-[44px] min-h-[44px] flex items-center justify-center md:hidden"
            aria-label="Filters"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
          </button>

          {/* Always-present dropzone input (used by FAB on mobile via openDropzone()) */}
          <input {...getInputProps()} className="sr-only" />

          {/* Upload button — hidden on mobile (FAB handles it) */}
          <div {...getRootProps()} className="hidden md:block cursor-pointer">
            <button
              disabled={uploading}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 rounded-xl hover:from-amber-400 hover:to-amber-500 disabled:opacity-50 transition-all shadow-lg shadow-amber-500/20 text-sm font-medium font-display"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              {uploading ? t('uploading') : t('upload')}
            </button>
          </div>

          {/* Upload bucket selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-text-muted">{t('upload_to') || 'Upload to:'}</span>
            <select
              value={uploadBucket}
              onChange={(e) => setUploadBucket(e.target.value as 'public' | 'confidential')}
              disabled={uploading}
              className="px-2 py-1.5 bg-vault-800/50 border border-white/[0.08] rounded-lg text-xs text-text-secondary focus:outline-none focus:ring-2 focus:ring-amber-500/30 transition-all"
            >
              <option value="public">{t('bucket_public')}</option>
              {canAccessConf && (
                <option value="confidential">{t('bucket_confidential')}</option>
              )}
            </select>
          </div>
        </div>
      </div>

      {/* Drag active overlay */}
      {isDragActive && (
        <div className="fixed inset-0 bg-amber-500/10 backdrop-blur-sm z-40 flex items-center justify-center">
          <div className="bg-vault-900 border border-amber-500/30 rounded-2xl shadow-glow-lg p-8 text-center">
            <svg
              className="w-16 h-16 text-amber-400 mx-auto mb-4 animate-bounce"
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
            <p className="text-lg font-medium text-text-primary font-display">{t('drop_files_here')}</p>
            <p className="text-sm text-text-muted mt-1">
              {t('max_file_size', { size: formatFileSize(MAX_FILE_SIZE) })}
            </p>
          </div>
        </div>
      )}

      {/* Error messages */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-300 px-4 py-3 rounded-xl mb-6 flex items-center gap-2">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      )}

      {/* Success messages */}
      {success && (
        <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 px-4 py-3 rounded-xl mb-6 flex items-center gap-2">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {success}
        </div>
      )}

      {/* File queue */}
      {fileQueue.length > 0 && (
        <div className="bg-vault-900/60 border border-white/[0.06] rounded-2xl overflow-hidden mb-6 shadow-card">
          <div className="flex items-center justify-between px-4 py-3 bg-vault-800/30 border-b border-white/[0.06]">
            <h3 className="font-medium text-text-primary text-sm font-display">
              {t('upload_queue', { count: fileQueue.length })}
            </h3>
            <button onClick={clearQueue} className="text-xs text-text-muted hover:text-text-secondary transition-colors">
              {t('clear_completed')}
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {fileQueue.map((item) => (
              <div key={item.id} className="px-4 py-3 border-b border-white/[0.04] last:border-b-0">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    {item.status === 'pending' && (
                      <svg className="w-5 h-5 text-text-muted/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {item.status === 'uploading' && (
                      <div className="w-5 h-5 flex-shrink-0">
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-amber-400"></div>
                      </div>
                    )}
                    {item.status === 'success' && (
                      <svg className="w-5 h-5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {item.status === 'error' && (
                      <svg className="w-5 h-5 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                    {item.status === 'rejected' && (
                      <svg className="w-5 h-5 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    )}

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{item.file.name}</p>
                      <p className="text-xs text-text-muted">
                        {formatFileSize(item.file.size)}
                        {item.error && <span className="text-red-400 ml-2">{item.error}</span>}
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={() => removeFromQueue(item.id)}
                    className="p-1 text-text-muted/50 hover:text-text-secondary ml-2 transition-colors"
                    disabled={item.status === 'uploading'}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {(item.status === 'uploading' || item.status === 'pending') && (
                  <div className="w-full bg-vault-700/50 rounded-full h-1.5 overflow-hidden">
                    <div
                      className={`h-1.5 rounded-full transition-all duration-300 ${
                        item.status === 'pending' ? 'bg-vault-600' : 'bg-gradient-to-r from-amber-500 to-amber-400'
                      }`}
                      style={{ width: item.status === 'pending' ? '0%' : `${item.progress}%` }}
                    ></div>
                  </div>
                )}

                {item.status === 'success' && (
                  <div className="text-xs text-emerald-400">{t('upload_complete')}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dropzone area — hidden on mobile (FAB handles upload) */}
      {!isMobile && (
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-2xl p-8 mb-6 text-center transition-all cursor-pointer ${
          isDragActive ? 'border-amber-500/50 bg-amber-500/5' : 'border-white/[0.08] hover:border-white/[0.15] hover:bg-white/[0.02]'
        }`}
      >
        <input {...getInputProps()} />
        <svg
          className="w-12 h-12 text-text-muted/30 mx-auto mb-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>
        <p className="text-text-muted mb-2">
          {isDragActive ? t('drop_files_here') : t('drag_drop_hint')}
        </p>
        <p className="text-xs text-text-muted/50">
          {t('max_file_size', { size: formatFileSize(MAX_FILE_SIZE) })} •{' '}
          {t('max_batch_size', { size: formatFileSize(MAX_BATCH_SIZE) })}
        </p>
      </div>
      )}

      {/* Documents table/cards */}
      <div className="bg-vault-900/60 border border-white/[0.06] rounded-2xl overflow-hidden shadow-card" id="documents-list-container">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-10 h-10 border-2 border-amber-400/30 border-t-amber-400 rounded-full animate-spin"></div>
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center py-12">
            <svg
              className="w-16 h-16 text-text-muted/20 mx-auto mb-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-text-muted">{t('no_documents')}</p>
          </div>
        ) : (
          <>
            {/* Mobile card list */}
            <PullToRefresh onRefresh={refreshDocuments}>
            <div className="block md:hidden divide-y divide-white/[0.04]">
              {documents.map((doc) => (
                <div key={doc.id} className="px-4 py-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-text-primary truncate text-sm">{doc.original_filename || doc.filename}</p>
                      <p className="text-xs text-text-muted/50 mt-0.5">{doc.mime_type}</p>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded-lg text-xs font-medium flex-shrink-0 ${
                        doc.bucket === 'confidential'
                          ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                          : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      }`}
                    >
                      {doc.bucket === 'confidential' ? t('bucket_confidential') : t('bucket_public')}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-text-muted">
                    <span className={`px-1.5 py-0.5 rounded-lg font-medium ${getStatusColor(doc.status)}`}>
                      {t(`status_${doc.status}`)}
                    </span>
                    <span>{formatFileSize(doc.file_size)}</span>
                    {doc.page_count && <span>{doc.page_count}p</span>}
                    <span>{formatDate(doc.created_at)}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => handleDownload(doc.id, doc.original_filename || doc.filename)}
                      className="flex items-center gap-1 text-xs text-amber-400/80 hover:text-amber-400 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      {tCommon('download')}
                    </button>
                    {isAdmin && (
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="flex items-center gap-1 text-xs text-red-400/80 hover:text-red-400 transition-colors"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        {tCommon('delete')}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            </PullToRefresh>

            {/* Desktop table */}
            <div className="hidden md:block">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/[0.06] bg-vault-800/20">
                    <th
                      className="text-left py-3 px-6 text-xs font-medium text-text-muted uppercase tracking-wider cursor-pointer hover:text-text-secondary select-none"
                      onClick={() => handleSort('original_filename')}
                    >
                      <span className="flex items-center gap-1">
                        {t('filename')}
                        {sortBy === 'original_filename' && (
                          <span className="text-amber-400">{sortDir === 'asc' ? '↑' : '↓'}</span>
                        )}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider">
                      {t('bucket')}
                    </th>
                    <th
                      className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider cursor-pointer hover:text-text-secondary select-none"
                      onClick={() => handleSort('status')}
                    >
                      <span className="flex items-center gap-1">
                        {t('status')}
                        {sortBy === 'status' && <span className="text-amber-400">{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th
                      className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider cursor-pointer hover:text-text-secondary select-none"
                      onClick={() => handleSort('file_size')}
                    >
                      <span className="flex items-center gap-1">
                        {t('size')}
                        {sortBy === 'file_size' && <span className="text-amber-400">{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider hidden sm:table-cell">
                      {t('page_count')}
                    </th>
                    <th
                      className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider cursor-pointer hover:text-text-secondary select-none"
                      onClick={() => handleSort('created_at')}
                    >
                      <span className="flex items-center gap-1">
                        {t('created_at')}
                        {sortBy === 'created_at' && <span className="text-amber-400">{sortDir === 'asc' ? '↑' : '↓'}</span>}
                      </span>
                    </th>
                    <th className="text-left py-3 px-4 text-xs font-medium text-text-muted uppercase tracking-wider">
                      {t('actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc.id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 px-6">
                        <div className="font-medium text-text-primary text-sm">{doc.original_filename || doc.filename}</div>
                        <div className="text-xs text-text-muted/50 mt-0.5">{doc.mime_type}</div>
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-1 rounded-lg text-xs font-medium ${
                            doc.bucket === 'confidential'
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                              : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          }`}
                        >
                          {doc.bucket === 'confidential'
                            ? t('bucket_confidential')
                            : t('bucket_public')}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-1 rounded-lg text-xs font-medium ${getStatusColor(doc.status)}`}>
                          {t(`status_${doc.status}`)}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-sm text-text-secondary">
                        {formatFileSize(doc.file_size)}
                      </td>
                      <td className="py-3 px-4 text-sm text-text-secondary hidden sm:table-cell">
                        {doc.page_count || '—'}
                      </td>
                      <td className="py-3 px-4 text-sm text-text-secondary">
                        {formatDate(doc.created_at)}
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleDownload(doc.id, doc.original_filename || doc.filename)}
                            className="p-1.5 text-text-muted hover:text-amber-400 hover:bg-amber-500/5 rounded-lg transition-all"
                            title={tCommon('download')}
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                          </button>
                          {isAdmin && (
                            <button
                              onClick={() => handleDelete(doc.id)}
                              className="p-1.5 text-text-muted hover:text-red-400 hover:bg-red-500/5 rounded-lg transition-all"
                              title={tCommon('delete')}
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
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
                <div className="flex items-center justify-between px-6 py-4 border-t border-white/[0.06]">
                  <p className="text-sm text-text-muted">
                    Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, total)} of{' '}
                    {total}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="px-3 py-1.5 text-sm bg-vault-800/50 border border-white/[0.08] rounded-lg hover:bg-vault-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all text-text-secondary"
                    >
                      {tCommon('previous')}
                    </button>
                    <span className="px-3 py-1.5 text-sm text-text-muted">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="px-3 py-1.5 text-sm bg-vault-800/50 border border-white/[0.08] rounded-lg hover:bg-vault-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all text-text-secondary"
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

      {/* FAB — mobile upload trigger */}
      <FAB onClick={() => openDropzone()} label={t('upload')} />

      {/* Filter bottom sheet — mobile only */}
      <MobileBottomSheet
        open={showFilterSheet}
        onClose={() => setShowFilterSheet(false)}
        title="Filtres"
        heightPercent={55}
      >
        <div className="space-y-5">
          {/* Bucket filter */}
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2">{t('bucket')}</p>
            <div className="flex flex-wrap gap-2">
              {(['all', 'public', ...(canAccessConf ? ['confidential'] : [])] as const).map((b) => (
                <button
                  key={b}
                  onClick={() => { setBucketFilter(b as typeof bucketFilter); setShowFilterSheet(false); }}
                  className={`px-4 py-2 rounded-xl text-sm font-medium border transition-all min-h-[44px] ${
                    bucketFilter === b
                      ? 'bg-amber-500/20 border-amber-500/40 text-amber-400'
                      : 'bg-vault-800 border-white/[0.06] text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {b === 'all' ? t('all_buckets') : b === 'public' ? t('bucket_public') : t('bucket_confidential')}
                </button>
              ))}
            </div>
          </div>

          {/* Sort options */}
          <div>
            <p className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2">{t('sort_by') || 'Sort'}</p>
            <div className="flex flex-col gap-2">
              {(
                [
                  { key: 'created_at', label: t('created_at') },
                  { key: 'original_filename', label: t('filename') },
                  { key: 'file_size', label: t('size') },
                  { key: 'status', label: t('status') },
                ] as { key: typeof sortBy; label: string }[]
              ).map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => { handleSort(key); setShowFilterSheet(false); }}
                  className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm border transition-all min-h-[44px] ${
                    sortBy === key
                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
                      : 'bg-vault-800 border-white/[0.06] text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <span>{label}</span>
                  {sortBy === key && (
                    <span className="text-amber-400 text-xs">{sortDir === 'asc' ? '↑' : '↓'}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      </MobileBottomSheet>
    </div>
  );
}
