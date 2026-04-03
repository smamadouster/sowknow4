'use client';

import { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';

interface BatchUploadResult {
  batch_id: string;
  document_ids: string[];
  total_files: number;
  accepted_files: number;
  rejected_files: number;
}

interface BatchUploaderProps {
  onComplete?: (result: BatchUploadResult) => void;
  onError?: (error: string) => void;
  maxFiles?: number;
}

export default function BatchUploader({
  onComplete,
  onError,
  maxFiles = 20,
}: BatchUploaderProps) {
  const t = useTranslations('documents');
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchUploadResult | null>(null);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = Array.from(e.target.files ?? []);
      if (selected.length > maxFiles) {
        const msg = `Maximum ${maxFiles} files per batch upload`;
        setError(msg);
        onError?.(msg);
        return;
      }
      setFiles(selected);
      setError(null);
    },
    [maxFiles, onError]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const dropped = Array.from(e.dataTransfer.files);
      if (dropped.length > maxFiles) {
        const msg = `Maximum ${maxFiles} files per batch upload`;
        setError(msg);
        onError?.(msg);
        return;
      }
      setFiles(dropped);
      setError(null);
    },
    [maxFiles, onError]
  );

  const handleUpload = async () => {
    if (files.length === 0) return;

    setUploading(true);
    setProgress(0);
    setError(null);

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    try {
      // Simulate progress during upload
      const progressInterval = setInterval(() => {
        setProgress((prev) => Math.min(prev + 10, 90));
      }, 200);

      const res = await fetch('/api/v1/documents/upload-batch', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });

      clearInterval(progressInterval);
      setProgress(100);

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = data?.detail ?? `Upload failed (HTTP ${res.status})`;
        setError(msg);
        onError?.(msg);
        return;
      }

      const data: BatchUploadResult = await res.json();
      setResult(data);
      onComplete?.(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      setError(msg);
      onError?.(msg);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="w-full space-y-4">
      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        className="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center hover:border-yellow-400 transition-colors"
      >
        <input
          id="batch-upload-input"
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png,.tiff,.mp4,.avi,.mov,.mkv,.mp3,.wav,.ogg,.flac,.aac,.wma,.m4a"
          onChange={handleFileChange}
          className="sr-only"
          aria-label="Select files for batch upload"
        />
        <label
          htmlFor="batch-upload-input"
          className="cursor-pointer flex flex-col items-center gap-2"
        >
          <svg
            className="w-10 h-10 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <span className="text-sm text-gray-600">
            {files.length > 0
              ? `${files.length} file${files.length > 1 ? 's' : ''} selected`
              : `Drop files here or click to browse (max ${maxFiles})`}
          </span>
        </label>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <ul className="text-sm text-gray-700 space-y-1 max-h-40 overflow-y-auto border rounded-lg p-2">
          {files.map((f, i) => (
            <li key={i} className="flex justify-between">
              <span className="truncate max-w-xs">{f.name}</span>
              <span className="text-gray-400 ml-2 shrink-0">
                {(f.size / 1024).toFixed(1)} KB
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Error banner */}
      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
          {error}
        </div>
      )}

      {/* Progress bar */}
      {uploading && (
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-yellow-400 h-2 rounded-full transition-all duration-200"
            style={{ width: `${progress}%` }}
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      )}

      {/* Success result */}
      {result && !uploading && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded text-sm">
          <p className="font-medium">
            {result.accepted_files} / {result.total_files} files queued for processing
          </p>
          <p className="text-xs text-green-600 mt-1">Batch ID: {result.batch_id}</p>
        </div>
      )}

      {/* Upload button */}
      <button
        type="button"
        onClick={handleUpload}
        disabled={files.length === 0 || uploading}
        aria-busy={uploading}
        className="w-full bg-yellow-400 hover:bg-yellow-500 disabled:bg-gray-200 disabled:text-gray-400 text-gray-900 font-semibold py-2 px-4 rounded-lg transition-colors"
      >
        {uploading ? 'Uploading…' : `Upload ${files.length > 0 ? files.length : ''} File${files.length !== 1 ? 's' : ''}`}
      </button>
    </div>
  );
}
