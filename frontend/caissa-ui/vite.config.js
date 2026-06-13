import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// lodash (via recharts) carries `Function('return this')()` as a last-resort
// global-object fallback. It never runs in browsers, but its mere presence
// trips CSP eval reporting — replace it with globalThis, which is what that
// idiom computes anyway.
const stripFunctionEval = {
  name: 'strip-function-eval',
  renderChunk(code) {
    if (!code.includes('return this')) return null;
    return code.replace(/Function\((["'])return this\1\)\(\)/g, 'globalThis');
  },
};

export default defineConfig({
  plugins: [react(), stripFunctionEval],
  server: {
    port: 3000,
    open: true,
  },
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          react:  ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
});
