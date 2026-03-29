'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { useAuthStore } from '@/lib/store';
import { getCsrfToken } from '@/lib/api';

// ---------- Document Preview helpers ----------

const PREVIEWABLE_MIME_TYPES: Record<string, 'csv' | 'xml' | 'json' | 'text' | 'image' | 'pdf'> = {
  'text/csv': 'csv',
  'application/csv': 'csv',
  'text/xml': 'xml',
  'application/xml': 'xml',
  'application/json': 'json',
  'text/plain': 'text',
  'text/markdown': 'text',
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/gif': 'image',
  'image/bmp': 'image',
  'application/pdf': 'pdf',
};

function getPreviewType(mimeType: string): 'csv' | 'xml' | 'json' | 'text' | 'image' | 'pdf' | null {
  return PREVIEWABLE_MIME_TYPES[mimeType] ?? null;
}

function parseCsv(raw: string): string[][] {
  const rows: string[][] = [];
  let current = '';
  let inQuotes = false;
  let row: string[] = [];

  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (inQuotes) {
      if (ch === '"' && raw[i + 1] === '"') {
        current += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        row.push(current);
        current = '';
      } else if (ch === '\n' || (ch === '\r' && raw[i + 1] === '\n')) {
        row.push(current);
        current = '';
        if (row.some(c => c.trim())) rows.push(row);
        row = [];
        if (ch === '\r') i++;
      } else {
        current += ch;
      }
    }
  }
  if (current || row.length) {
    row.push(current);
    if (row.some(c => c.trim())) rows.push(row);
  }
  return rows;
}

function CsvPreview({ content }: { content: string }) {
  const rows = parseCsv(content);
  if (rows.length === 0) return <p className="text-sm text-gray-400">Empty CSV</p>;

  const header = rows[0];
  const body = rows.slice(1);
  const maxRows = 200;

  return (
    <div className="overflow-auto max-h-[500px] border border-gray-200 rounded-lg">
      <table className="min-w-full text-xs">
        <thead className="bg-gray-100 sticky top-0">
          <tr>
            {header.map((cell, i) => (
              <th key={i} className="px-3 py-2 text-left font-semibold text-gray-700 border-b border-gray-200 whitespace-nowrap">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, maxRows).map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-gray-800 border-b border-gray-100 whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length > maxRows && (
        <p className="text-xs text-gray-400 p-2 text-center">
          Showing {maxRows} of {body.length} rows
        </p>
      )}
    </div>
  );
}

function XmlPreview({ content }: { content: string }) {
  return (
    <div className="overflow-auto max-h-[500px] border border-gray-200 rounded-lg">
      <pre className="text-xs p-4 bg-gray-50 whitespace-pre-wrap break-words font-mono leading-relaxed">
        {content}
      </pre>
    </div>
  );
}

function DocumentPreview({ docId, mimeType, apiBase }: { docId: string; mimeType: string; apiBase: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const previewType = getPreviewType(mimeType);

  const fetchContent = useCallback(async () => {
    if (!previewType) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await fetch(`${apiBase}/v1/documents/${docId}/download`, {
        credentials: 'include',
      });
      if (!res.ok) {
        setPreviewError('Failed to load preview');
        return;
      }
      if (previewType === 'image') {
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      } else if (previewType === 'pdf') {
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      } else {
        const text = await res.text();
        setContent(text);
      }
    } catch {
      setPreviewError('Failed to load preview');
    } finally {
      setPreviewLoading(false);
    }
  }, [docId, apiBase, previewType]);

  // Clean up blob URL on unmount
  useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  if (!previewType) return null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
      <button
        onClick={() => {
          setExpanded(v => !v);
          if (!expanded && content === null && blobUrl === null) fetchContent();
        }}
        className="flex items-center justify-between w-full"
      >
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Preview
        </h2>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-4">
          {previewLoading && (
            <div className="flex items-center gap-3 text-sm text-gray-400 py-4">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              Loading preview...
            </div>
          )}
          {previewError && (
            <p className="text-sm text-red-500">{previewError}</p>
          )}
          {!previewLoading && !previewError && content !== null && previewType === 'csv' && (
            <CsvPreview content={content} />
          )}
          {!previewLoading && !previewError && content !== null && previewType === 'xml' && (
            <XmlPreview content={content} />
          )}
          {!previewLoading && !previewError && content !== null && previewType === 'json' && (
            <div className="overflow-auto max-h-[500px] border border-gray-200 rounded-lg">
              <pre className="text-xs p-4 bg-gray-50 whitespace-pre-wrap break-words font-mono leading-relaxed">
                {(() => { try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; } })()}
              </pre>
            </div>
          )}
          {!previewLoading && !previewError && content !== null && previewType === 'text' && (
            <div className="overflow-auto max-h-[500px] border border-gray-200 rounded-lg">
              <pre className="text-xs p-4 bg-gray-50 whitespace-pre-wrap break-words font-mono leading-relaxed">
                {content}
              </pre>
            </div>
          )}
          {!previewLoading && !previewError && blobUrl && previewType === 'image' && (
            <div className="flex justify-center border border-gray-200 rounded-lg bg-gray-50 p-4">
              <img src={blobUrl} alt="Document preview" className="max-h-[500px] max-w-full object-contain" />
            </div>
          )}
          {!previewLoading && !previewError && blobUrl && previewType === 'pdf' && (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <iframe src={blobUrl} className="w-full h-[500px]" title="PDF preview" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface Tag {
  id: string;
  name: string;
}

interface Document {
  id: string;
  filename: string;
  original_filename: string;
  bucket: string;
  status: string;
  mime_type: string;
  file_size: number;
  page_count: number | null;
  chunk_count: number | null;
  ocr_processed: boolean;
  embedding_generated: boolean;
  language: string | null;
  created_at: string;
  updated_at: string;
  document_metadata: Record<string, unknown>;
  tags: Tag[];
}

interface EditForm {
  filename: string;
  bucket: string;
  language: string;
}

interface SimilarDocument {
  id: string;
  filename: string;
  similarity_score: number;
  created_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

const TAG_COLORS = [
  'bg-blue-100 text-blue-700',
  'bg-purple-100 text-purple-700',
  'bg-pink-100 text-pink-700',
  'bg-teal-100 text-teal-700',
  'bg-indigo-100 text-indigo-700',
];

export default function DocumentDetailPage() {
  const t = useTranslations('documents');
  const tCommon = useTranslations('common');
  const params = useParams();
  const locale = params.locale as string;
  const id = params.id as string;

  const { user } = useAuthStore();
  const isAdmin = user?.role === 'admin';

  const [doc, setDoc] = useState<Document | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Edit modal state
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState<EditForm>({
    filename: '',
    bucket: 'public',
    language: 'fr',
  });
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Metadata collapsible
  const [metaExpanded, setMetaExpanded] = useState(false);

  // Related documents
  const [similarDocs, setSimilarDocs] = useState<SimilarDocument[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);

  const fetchDocument = async () => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const res = await fetch(`${API_BASE}/v1/documents/${id}`, {
        credentials: 'include',
      });
      if (res.status === 404) {
        setNotFound(true);
        return;
      }
      if (!res.ok) {
        setError(tCommon('error'));
        return;
      }
      const data: Document = await res.json();
      setDoc(data);
    } catch (e) {
      console.error('Error fetching document:', e);
      setError(tCommon('error'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (id) fetchDocument();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!doc || doc.status !== 'indexed') return;
    const fetchSimilar = async () => {
      setSimilarLoading(true);
      try {
        const res = await fetch(`${API_BASE}/v1/documents/${doc.id}/similar?limit=6`, {
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setSimilarDocs(data.similar || []);
        }
      } catch (e) {
        console.error('Error fetching similar documents:', e);
      } finally {
        setSimilarLoading(false);
      }
    };
    fetchSimilar();
  }, [doc?.id, doc?.status]);

  const handleDownload = async () => {
    if (!doc) return;
    try {
      const res = await fetch(`${API_BASE}/v1/documents/${doc.id}/download`, {
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
      a.download = doc.original_filename || doc.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Download error:', e);
      setError(tCommon('error'));
    }
  };

  const openEditModal = () => {
    if (!doc) return;
    setEditForm({
      filename: doc.filename,
      bucket: doc.bucket,
      language: doc.language || 'fr',
    });
    setEditError(null);
    setEditOpen(true);
  };

  const handleSave = async () => {
    if (!doc) return;
    setSaving(true);
    setEditError(null);
    try {
      const res = await fetch(`${API_BASE}/v1/documents/${doc.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        body: JSON.stringify({
          filename: editForm.filename,
          bucket: editForm.bucket,
          language: editForm.language,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setEditError(data?.detail || tCommon('error'));
        return;
      }
      setEditOpen(false);
      setSuccess(t('edit_success'));
      setTimeout(() => setSuccess(null), 4000);
      await fetchDocument();
    } catch (e) {
      console.error('Save error:', e);
      setEditError(tCommon('error'));
    } finally {
      setSaving(false);
    }
  };

  const metaKeys = doc?.document_metadata ? Object.keys(doc.document_metadata) : [];

  // ---- Loading state ----
  if (loading) {
    return (
      <div className="p-6 max-w-5xl mx-auto flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        <span className="ml-4 text-gray-500">{t('loading')}</span>
      </div>
    );
  }

  // ---- Not found state ----
  if (notFound || !doc) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <Link
          href={`/${locale}/documents`}
          className="text-sm text-blue-600 hover:underline flex items-center gap-1 mb-6"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {tCommon('back')}
        </Link>
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-12 text-center">
          <svg className="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <p className="text-gray-500 text-lg">{t('not_found')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Back link + breadcrumb */}
      <div className="flex items-center gap-2 mb-6 text-sm text-gray-500">
        <Link
          href={`/${locale}/documents`}
          className="text-blue-600 hover:underline flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {tCommon('back')}
        </Link>
        <span>/</span>
        <Link href={`/${locale}/documents`} className="hover:underline">
          {t('title')}
        </Link>
        <span>/</span>
        <span className="text-gray-900 truncate max-w-xs">{doc.original_filename || doc.filename}</span>
      </div>

      {/* Alert messages */}
      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-3 rounded-lg mb-4 flex items-center gap-2">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-50 text-green-600 px-4 py-3 rounded-lg mb-4 flex items-center gap-2">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {success}
        </div>
      )}

      {/* Header card */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-gray-900 break-words">
              {doc.original_filename || doc.filename}
            </h1>
            {doc.original_filename && doc.original_filename !== doc.filename && (
              <p className="text-sm text-gray-400 mt-1 truncate">{doc.filename}</p>
            )}
            <div className="flex items-center flex-wrap gap-2 mt-3">
              {/* Bucket badge */}
              <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                doc.bucket === 'confidential'
                  ? 'bg-orange-100 text-orange-700'
                  : 'bg-green-100 text-green-700'
              }`}>
                {doc.bucket === 'confidential' ? t('bucket_confidential') : t('bucket_public')}
              </span>
              {/* Status badge */}
              <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${getStatusColor(doc.status)}`}>
                {t(`status_${doc.status}`)}
              </span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleDownload}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              {tCommon('download')}
            </button>
            {isAdmin && (
              <button
                onClick={openEditModal}
                className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                {tCommon('edit')}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Metadata grid */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
          {t('metadata')}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('size')}</span>
            <span className="text-sm text-gray-900">{formatFileSize(doc.file_size)}</span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('type')}</span>
            <span className="text-sm text-gray-900 font-mono">{doc.mime_type}</span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('page_count')}</span>
            <span className="text-sm text-gray-900">{doc.page_count ?? '—'}</span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('language')}</span>
            <span className="text-sm text-gray-900">{doc.language || '—'}</span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('chunks')}</span>
            <span className="text-sm text-gray-900">{doc.chunk_count ?? '—'}</span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('ocr_processed')}</span>
            <span className={`text-sm font-medium ${doc.ocr_processed ? 'text-green-600' : 'text-gray-400'}`}>
              {doc.ocr_processed ? t('yes') : t('no')}
            </span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('embeddings')}</span>
            <span className={`text-sm font-medium ${doc.embedding_generated ? 'text-green-600' : 'text-gray-400'}`}>
              {doc.embedding_generated ? t('yes') : t('no')}
            </span>
          </div>

          <div className="flex items-start gap-3">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('created_at')}</span>
            <span className="text-sm text-gray-900">{formatDate(doc.created_at)}</span>
          </div>

          <div className="flex items-start gap-3 md:col-span-2">
            <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('updated_at')}</span>
            <span className="text-sm text-gray-900">{formatDate(doc.updated_at)}</span>
          </div>

          {/* Tags */}
          {doc.tags && doc.tags.length > 0 && (
            <div className="flex items-start gap-3 md:col-span-2">
              <span className="text-sm font-medium text-gray-500 w-32 flex-shrink-0">{t('tags')}</span>
              <div className="flex flex-wrap gap-1.5">
                {doc.tags.map((tag, idx) => (
                  <span
                    key={tag.id}
                    className={`px-2 py-0.5 rounded text-xs font-medium ${TAG_COLORS[idx % TAG_COLORS.length]}`}
                  >
                    {tag.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Document preview — CSV table, XML/JSON/TXT code, images, PDF */}
      <DocumentPreview docId={doc.id} mimeType={doc.mime_type} apiBase={API_BASE} />

      {/* Processing metadata section — collapsible */}
      {metaKeys.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
          <button
            onClick={() => setMetaExpanded(v => !v)}
            className="flex items-center justify-between w-full"
          >
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
              {metaExpanded ? t('hide_metadata') : t('show_metadata')}
            </h2>
            <svg
              className={`w-5 h-5 text-gray-400 transition-transform ${metaExpanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {metaExpanded && (
            <pre className="mt-4 text-xs text-gray-700 bg-gray-50 rounded-lg p-4 overflow-x-auto border border-gray-200 whitespace-pre-wrap break-words">
              {JSON.stringify(doc.document_metadata, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Text chunks placeholder */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          {t('chunks')}
        </h2>
        <div className="flex items-center gap-3 text-sm text-gray-500 bg-gray-50 rounded-lg p-4 border border-gray-200">
          <svg className="w-5 h-5 text-blue-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {t('chunks_note')}
        </div>
      </div>

      {/* Related documents — only shown for indexed documents */}
      {doc.status === 'indexed' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            {t('related_documents')}
          </h2>

          {similarLoading ? (
            <div className="flex items-center gap-3 text-sm text-gray-400">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              {t('loading')}
            </div>
          ) : similarDocs.length === 0 ? (
            <p className="text-sm text-gray-400">{t('no_related_documents')}</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {similarDocs.map((similar) => (
                <Link
                  key={similar.id}
                  href={`/${locale}/documents/${similar.id}`}
                  className="group block p-4 rounded-lg border border-gray-200 hover:border-blue-300 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="text-sm font-medium text-gray-900 group-hover:text-blue-600 truncate flex-1">
                      {similar.filename}
                    </p>
                    <span className="text-xs font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded flex-shrink-0">
                      {Math.round(similar.similarity_score * 100)}%
                    </span>
                  </div>
                  <p className="text-xs text-gray-400">{formatDate(similar.created_at)}</p>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Edit modal */}
      {editOpen && isAdmin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">{t('edit_metadata')}</h2>
              <button
                onClick={() => setEditOpen(false)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {editError && (
                <div className="bg-red-50 text-red-600 px-3 py-2 rounded-lg text-sm flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {editError}
                </div>
              )}

              {/* Filename / display name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  {t('filename')}
                </label>
                <input
                  type="text"
                  value={editForm.filename}
                  onChange={e => setEditForm(f => ({ ...f, filename: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              {/* Bucket */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  {t('bucket')}
                </label>
                <select
                  value={editForm.bucket}
                  onChange={e => setEditForm(f => ({ ...f, bucket: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="public">{t('bucket_public')}</option>
                  <option value="confidential">{t('bucket_confidential')}</option>
                </select>
              </div>

              {/* Language */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  {t('language')}
                </label>
                <select
                  value={editForm.language}
                  onChange={e => setEditForm(f => ({ ...f, language: e.target.value }))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="fr">Français</option>
                  <option value="en">English</option>
                  <option value="multi">Multilingual</option>
                  <option value="unknown">Unknown</option>
                </select>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
              <button
                onClick={() => setEditOpen(false)}
                disabled={saving}
                className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editForm.filename.trim()}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving && (
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                )}
                {tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
