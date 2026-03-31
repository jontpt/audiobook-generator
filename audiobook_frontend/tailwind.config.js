/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        dark: {
          50:  '#f0f0f8',
          100: '#e0e0f0',
          200: '#c0c0e0',
          300: '#9090c8',
          400: '#6060a8',
          500: '#404088',
          600: '#303068',
          700: '#202048',
          800: '#141428',
          900: '#0d0d1a',
          950: '#07070d',
        },
        brand: {
          50:  '#f0e8ff',
          100: '#e0cfff',
          200: '#c49fff',
          300: '#a86eff',
          400: '#8c3dff',
          500: '#7c2dfa',
          600: '#6b1de8',
          700: '#5a0fc8',
          800: '#4a08a8',
          900: '#3a0488',
        },
        accent: {
          teal:   '#00d4b4',
          purple: '#9b59ff',
          pink:   '#ff4da6',
          amber:  '#ffb020',
          blue:   '#3d9eff',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #7c2dfa 0%, #00d4b4 100%)',
        'gradient-dark':  'linear-gradient(180deg, #0d0d1a 0%, #141428 100%)',
        'gradient-card':  'linear-gradient(145deg, rgba(124,45,250,0.08) 0%, rgba(0,212,180,0.04) 100%)',
      },
      boxShadow: {
        'glow-brand':  '0 0 30px rgba(124,45,250,0.35)',
        'glow-teal':   '0 0 30px rgba(0,212,180,0.30)',
        'glow-sm':     '0 0 12px rgba(124,45,250,0.25)',
        'card':        '0 4px 24px rgba(0,0,0,0.40)',
        'card-hover':  '0 8px 40px rgba(0,0,0,0.55)',
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float':        'float 3s ease-in-out infinite',
        'shimmer':      'shimmer 2s linear infinite',
        'spin-slow':    'spin 3s linear infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%':      { transform: 'translateY(-8px)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition:  '200% 0' },
        }
      },
    },
  },
  plugins: [],
}
