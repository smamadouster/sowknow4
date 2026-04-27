"use client";

interface LoadingStateProps {
  step?: string;
  progressPercent?: number;
}

const STEPS = [
  { key: "parsing", label: "Understanding your request…" },
  { key: "resolving", label: "Finding the right entity…" },
  { key: "retrieving", label: "Searching your vault…" },
  { key: "analysing", label: "Extracting milestones & patterns…" },
  { key: "generating", label: "Writing your report…" },
];

export default function LoadingState({ step = "parsing", progressPercent = 0 }: LoadingStateProps) {
  const activeIndex = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="w-full max-w-2xl mx-auto py-12">
      <div className="space-y-6">
        {STEPS.map((s, idx) => {
          const isActive = idx === activeIndex;
          const isDone = idx < activeIndex;
          return (
            <div
              key={s.key}
              className={`flex items-center gap-4 transition-opacity duration-500 ${
                isActive ? "opacity-100" : isDone ? "opacity-60" : "opacity-30"
              }`}
            >
              <div
                className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold ${
                  isDone
                    ? "bg-green-500 text-white"
                    : isActive
                    ? "bg-blue-600 text-white animate-pulse"
                    : "bg-gray-200 dark:bg-gray-700 text-gray-500"
                }`}
              >
                {isDone ? (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  idx + 1
                )}
              </div>
              <span
                className={`text-sm font-medium ${
                  isActive
                    ? "text-gray-900 dark:text-white"
                    : "text-gray-500 dark:text-gray-400"
                }`}
              >
                {s.label}
              </span>
              {isActive && (
                <div className="ml-auto w-24 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-600 rounded-full transition-all duration-500"
                    style={{ width: `${Math.max(10, progressPercent)}%` }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
