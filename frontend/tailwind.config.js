/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      spacing: {
        'safe-bottom': 'env(safe-area-inset-bottom, 0px)',
        'safe-top': 'env(safe-area-inset-top, 0px)',
        'bottom-bar': 'var(--bottom-bar-total)',
      },
      colors: {
        vault: {
          50: '#f8f9fb',
          100: '#f1f2f6',
          200: '#e4e6ef',
          300: '#d1d4e2',
          400: '#a8adc4',
          500: '#8289a6',
          600: '#656b88',
          700: '#4e536e',
          800: '#3a3e56',
          900: '#252836',
          950: '#1a1d27',
          1000: '#0f1117',
        },
        amber: {
          450: '#e8920d',
        },
        primary: {
          background: '#FFFFFF',
          dark: '#1A1A2E',
          yellow: '#FFEB3B',
          blue: '#2196F3',
          pink: '#E91E63',
          green: '#4CAF50',
          gray: '#E0E0E0',
        },
      },
      fontFamily: {
        display: ['Outfit', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'Source Sans 3', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      letterSpacing: {
        'heading': '-0.03em',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'typing': 'typing 1.5s steps(40, end)',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'shimmer': 'shimmer 2s linear infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        typing: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(245, 158, 11, 0.3), 0 0 20px rgba(245, 158, 11, 0.1)' },
          '100%': { boxShadow: '0 0 10px rgba(245, 158, 11, 0.5), 0 0 40px rgba(245, 158, 11, 0.2)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'vault-gradient': 'linear-gradient(135deg, #0f1117 0%, #1a1d27 50%, #252836 100%)',
        'amber-glow': 'linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, rgba(217, 119, 6, 0.05) 100%)',
        'glass': 'linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.02) 100%)',
      },
      boxShadow: {
        'glow': '0 0 20px rgba(245, 158, 11, 0.15)',
        'glow-lg': '0 0 30px rgba(245, 158, 11, 0.2)',
        'inner-glow': 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
        'card': '0 4px 24px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2)',
        'card-hover': '0 8px 40px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3)',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
}
