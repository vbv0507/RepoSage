// Vercel injects this public build-time API URL. Local Vite uses /api proxy.
const configuredApiUrl = import.meta.env.VITE_API_URL?.replace(/\/$/, '');
export const API_BASE = configuredApiUrl || '';
