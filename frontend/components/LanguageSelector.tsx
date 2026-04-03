'use client';

import { useLocale } from 'next-intl';
import { useRouter, usePathname } from '@/i18n/routing';
import { useState, useEffect } from 'react';

const languages = [
  { code: 'fr', name: 'FR', label: 'Français' },
  { code: 'en', name: 'EN', label: 'English' },
];

export function LanguageSelector() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);
  const [currentLocale, setCurrentLocale] = useState(locale);

  useEffect(() => {
    setCurrentLocale(locale);
  }, [locale]);

  const handleLanguageChange = (newLocale: string) => {
    setCurrentLocale(newLocale);
    setIsOpen(false);

    if (typeof window !== 'undefined') {
      localStorage.setItem('preferred-locale', newLocale);
    }

    router.replace(pathname, { locale: newLocale });
  };

  const currentLanguage = languages.find((lang) => lang.code === currentLocale);

  return (
    <div className="relative inline-block text-left">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-text-muted bg-vault-800/50 border border-white/[0.08] rounded-lg hover:text-text-secondary hover:border-white/[0.12] focus:outline-none focus:ring-2 focus:ring-amber-500/30 transition-all font-display"
      >
        <span>{currentLanguage?.name}</span>
        <svg
          className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute right-0 z-20 mt-2 w-40 origin-top-right rounded-xl bg-vault-900 border border-white/[0.08] shadow-xl focus:outline-none">
            <div className="py-1">
              {languages.map((language) => (
                <button
                  key={language.code}
                  onClick={() => handleLanguageChange(language.code)}
                  className={`${
                    currentLocale === language.code
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'text-text-secondary hover:bg-white/[0.04]'
                  } group flex items-center w-full px-3 py-2 text-sm transition-colors`}
                >
                  <span className="font-medium">{language.name}</span>
                  <span className="ml-1 text-xs text-text-muted/50">{language.label}</span>
                  {currentLocale === language.code && (
                    <svg
                      className="ml-auto h-4 w-4 text-amber-400"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  )}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
