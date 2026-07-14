'use client';

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-vault-1000 flex items-center justify-center p-4">
      <div className="max-w-md w-full bg-vault-900/60 border border-white/[0.06] rounded-2xl p-8 text-center shadow-card backdrop-blur-md">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center shadow-lg shadow-amber-500/20">
          <svg
            className="w-8 h-8 text-vault-1000"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </div>

        <h1 className="text-2xl font-bold text-text-primary font-display mb-2">
          Something went wrong
        </h1>
        <p className="text-text-secondary text-sm mb-6">
          We encountered an unexpected error. You can try again or refresh the page.
        </p>

        {error.digest && (
          <p className="text-xs text-text-muted font-mono mb-6 break-all">
            Error ID: {error.digest}
          </p>
        )}

        <button
          onClick={reset}
          className="inline-flex items-center justify-center gap-2 px-6 py-2.5 bg-amber-500 text-vault-1000 rounded-xl font-medium hover:bg-amber-400 transition-colors"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
          </svg>
          Try again
        </button>
      </div>
    </div>
  );
}
