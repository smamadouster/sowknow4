"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { useRouter as useIntlRouter } from "@/i18n/routing";

// Disable static optimization for this client component
export const dynamic = 'force-dynamic';

interface GeneratedFolder {
  collection_id: string;
  topic: string;
  generated_content: string;
  sources_used: Array<{
    id: string;
    filename: string;
    bucket: string;
    created_at: string;
  }>;
  word_count: number;
  llm_used: string;
}

export default function SmartFoldersPage() {
  const t = useTranslations('smart_folders');
  const tCommon = useTranslations('common');
  const tDocuments = useTranslations('documents');
  const locale = useLocale();
  const intlRouter = useIntlRouter();

  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState("informative");
  const [length, setLength] = useState("medium");
  const [includeConfidential, setIncludeConfidential] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GeneratedFolder | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (!topic.trim()) return;

    setGenerating(true);
    setError(null);
    setResult(null);

    try {
      const token = localStorage.getItem("token");
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/smart-folders/generate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            topic,
            style,
            length,
            include_confidential: includeConfidential,
          }),
        }
      );

      if (response.ok) {
        const data: GeneratedFolder = await response.json();
        setResult(data);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || tDocuments('upload_error'));
      }
    } catch (err) {
      setError(tDocuments('upload_error'));
    } finally {
      setGenerating(false);
    }
  };

  const viewCollection = () => {
    if (result) {
      intlRouter.push(`/collections/${result.collection_id}`);
    }
  };

  const styles = [
    { value: "informative", label: t('style_informative'), desc: "Educational & clear" },
    { value: "professional", label: t('style_professional'), desc: "Formal business tone" },
    { value: "creative", label: t('style_creative'), desc: "Engaging & vivid" },
    { value: "casual", label: t('style_casual'), desc: "Friendly & relaxed" },
  ];

  const lengths = [
    { value: "short", label: t('length_short'), desc: "~300 words" },
    { value: "medium", label: t('length_medium'), desc: "~800 words" },
    { value: "long", label: t('length_long'), desc: "~2000 words" },
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 shadow">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            {t('title')}
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {t('generate')}
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Generation Form */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-6">
          <div className="space-y-4">
            {/* Topic Input */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {t('topic')}
              </label>
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder={t('topic_placeholder')}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                rows={3}
              />
            </div>

            {/* Style Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {t('style')}
              </label>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {styles.map((s) => (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => setStyle(s.value)}
                    className={`p-3 text-left rounded-lg border-2 transition ${
                      style === s.value
                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                        : "border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500"
                    }`}
                  >
                    <div className="font-medium text-sm text-gray-900 dark:text-white">
                      {s.label}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {s.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Length Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {t('length')}
              </label>
              <div className="grid grid-cols-3 gap-2">
                {lengths.map((l) => (
                  <button
                    key={l.value}
                    type="button"
                    onClick={() => setLength(l.value)}
                    className={`p-3 text-center rounded-lg border-2 transition ${
                      length === l.value
                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                        : "border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500"
                    }`}
                  >
                    <div className="font-medium text-sm text-gray-900 dark:text-white">
                      {l.label}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {l.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Confidential Toggle */}
            <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  {t('include_confidential')}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  Only available for users with confidential access
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIncludeConfidential(!includeConfidential)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  includeConfidential ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
                    includeConfidential ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>

            {/* Generate Button */}
            <button
              onClick={handleGenerate}
              disabled={generating || !topic.trim()}
              className="w-full px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
            >
              {generating ? t('generating') : t('generate')}
            </button>
          </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
            <p className="text-red-800 dark:text-red-200 text-sm">{error}</p>
          </div>
        )}

        {/* Result Display */}
        {result && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
            {/* Result Header */}
            <div className="p-6 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                    {result.topic}
                  </h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {result.word_count} {t('word_count')} • {result.llm_used === "gemini" ? t('llm_gemini') : t('llm_ollama')}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={viewCollection}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm"
                  >
                    {t('view_collection')}
                  </button>
                </div>
              </div>
            </div>

            {/* Generated Content */}
            <div className="p-6">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                {t('generated_content')}
              </h3>
              <div className="prose dark:prose-invert max-w-none">
                {result.generated_content.split("\n").map((paragraph, idx) => (
                  <p key={idx} className="mb-3 text-gray-700 dark:text-gray-300">
                    {paragraph}
                  </p>
                ))}
              </div>
            </div>

            {/* Sources */}
            {result.sources_used.length > 0 && (
              <div className="p-6 bg-gray-50 dark:bg-gray-700 border-t border-gray-200 dark:border-gray-600">
                <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                  {t('sources')} ({result.sources_used.length})
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {result.sources_used.map((source) => (
                    <div
                      key={source.id}
                      className="flex items-center gap-2 p-2 bg-white dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-600"
                    >
                      <span className="text-blue-600">📄</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                          {source.filename}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {new Date(source.created_at).toLocaleDateString(locale)}
                        </p>
                      </div>
                      {source.bucket === "confidential" && (
                        <span className="text-xs px-2 py-1 bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 rounded">
                          {tDocuments('bucket_confidential')}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Examples */}
        {result === null && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
            <h3 className="text-sm font-medium text-blue-900 dark:text-blue-200 mb-3">
              {t('examples')}
            </h3>
            <ul className="space-y-2">
              {[
                "Annual financial performance summary for 2023",
                "Key milestones and achievements from our projects",
                "Team productivity and collaboration improvements",
                "Customer satisfaction trends and feedback analysis",
                "Risk assessment and mitigation strategies",
              ].map((example) => (
                <li key={example}>
                  <button
                    onClick={() => setTopic(example)}
                    className="text-sm text-blue-700 dark:text-blue-300 hover:underline"
                  >
                    "{example}"
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
