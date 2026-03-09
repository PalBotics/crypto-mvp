/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        bg:      '#0d0f14',
        surface: '#13161e',
        card:    '#181b24',
        border:  '#222632',
        muted:   '#2a2f3d',
        'text-primary':   '#e2e4eb',
        'text-secondary': '#8b90a0',
        'text-dim':       '#555a6a',
        green:  { DEFAULT: '#22c55e', dim: '#166534' },
        red:    { DEFAULT: '#ef4444', dim: '#991b1b' },
        blue:   { DEFAULT: '#3b82f6', dim: '#1e40af' },
        orange: { DEFAULT: '#f97316', dim: '#9a3412' },
        yellow: { DEFAULT: '#eab308', dim: '#854d0e' },
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        'fade-in':   'fade-in 0.2s ease-out',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: 1 },
          '50%':      { opacity: 0.4 },
        },
        'fade-in': {
          from: { opacity: 0 },
          to:   { opacity: 1 },
        },
      },
    },
  },
  plugins: [],
}