/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        am: {
          bg:        '#f8fafc',   // page bg
          surface:   '#f1f5f9',   // subtle section bg
          white:     '#ffffff',
          indigo:    '#6366f1',   // primary
          'indigo-d':'#4f46e5',
          violet:    '#8b5cf6',   // provider / judge accent
          'violet-d':'#7c3aed',
          sky:       '#0ea5e9',   // buyer / info
          emerald:   '#10b981',   // success
          amber:     '#f59e0b',   // gold / rank
          rose:      '#f43f5e',   // error / danger
          text:      '#0f172a',   // slate-900
          'text-2':  '#475569',   // slate-600
          muted:     '#94a3b8',   // slate-400
          border:    '#e2e8f0',   // slate-200
          'border-sm':'#f1f5f9',  // slate-100
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'card':    '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        'card-md': '0 4px 16px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.05)',
        'card-lg': '0 12px 32px rgba(0,0,0,0.1), 0 4px 8px rgba(0,0,0,0.06)',
        'indigo':  '0 4px 14px rgba(99,102,241,0.28)',
        'violet':  '0 4px 14px rgba(139,92,246,0.28)',
        'inner':   'inset 0 1px 2px rgba(0,0,0,0.06)',
      },
      animation: {
        'fade-in':    'fadeIn 0.25s ease',
        'slide-up':   'slideUp 0.35s ease',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        'spin-slow':  'spin 2.5s linear infinite',
      },
      keyframes: {
        fadeIn:  { from: { opacity: 0 }, to: { opacity: 1 } },
        slideUp: { from: { opacity: 0, transform: 'translateY(10px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
}
