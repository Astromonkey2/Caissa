// Single source of truth for the backend base URL.
// Tolerates a VITE_API_URL set without a scheme (e.g. "api.up.railway.app"),
// which would otherwise be treated as a relative path by the browser.
const raw = (import.meta.env.VITE_API_URL || 'http://localhost:8000').trim();

export const API = (/^https?:\/\//i.test(raw) ? raw : `https://${raw}`).replace(/\/+$/, '');
