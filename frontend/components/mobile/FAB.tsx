'use client';

interface FABProps {
  onClick: () => void;
  label: string;
  icon?: React.ReactNode;
}

export default function FAB({ onClick, label, icon }: FABProps) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className="fab-position w-14 h-14 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 text-vault-1000 shadow-lg shadow-amber-500/30 flex items-center justify-center active:scale-95 transition-transform md:hidden"
    >
      {icon || (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
        </svg>
      )}
    </button>
  );
}
