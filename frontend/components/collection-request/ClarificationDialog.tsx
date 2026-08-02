"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { CollectionClarificationQuestion } from "@/lib/api";

interface ClarificationDialogProps {
  questions: CollectionClarificationQuestion[];
  round: number;
  maxRounds: number;
  loading: boolean;
  onSubmit: (answers: Record<string, string>) => void;
  onSkip: () => void;
}

export default function ClarificationDialog({
  questions,
  round,
  maxRounds,
  loading,
  onSubmit,
  onSkip,
}: ClarificationDialogProps) {
  const t = useTranslations("collection_requests");
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const setAnswer = (questionId: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  };

  const handleSubmit = () => {
    const filled = Object.fromEntries(
      Object.entries(answers).filter(([, v]) => v.trim() !== "")
    );
    onSubmit(filled);
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          {t("clarify_title")}
        </h2>
        <span className="text-xs px-2 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded">
          {t("clarify_round", { round, max: maxRounds })}
        </span>
      </div>

      <div className="space-y-6">
        {questions.map((question) => (
          <div key={question.id}>
            <p className="text-sm font-medium text-gray-900 dark:text-white mb-2">
              {question.text}
            </p>

            {question.options && question.options.length > 0 && (
              <div className="space-y-2 mb-2">
                {question.options.map((option) => (
                  <label
                    key={option.value}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition ${
                      answers[question.id] === option.value
                        ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                        : "border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700"
                    }`}
                  >
                    <input
                      type="radio"
                      name={question.id}
                      checked={answers[question.id] === option.value}
                      onChange={() => setAnswer(question.id, option.value)}
                      className="text-blue-600"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">
                      {option.label}
                    </span>
                  </label>
                ))}
              </div>
            )}

            <input
              type="text"
              value={answers[question.id] && question.options?.some((o) => o.value === answers[question.id]) ? "" : answers[question.id] || ""}
              onChange={(e) => setAnswer(question.id, e.target.value)}
              placeholder={t("your_answer")}
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white placeholder-gray-400"
            />
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-2">
        <button
          onClick={onSkip}
          disabled={loading}
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline transition disabled:opacity-50"
        >
          {t("skip")}
        </button>
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t("submitting") : t("submit_answers")}
        </button>
      </div>
    </div>
  );
}
