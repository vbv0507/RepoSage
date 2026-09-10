// Local Vite/Docker development uses the same-origin /api proxy. In Azure
// Container Apps, the frontend and backend are separate apps: Docker's
// `reposage-backend` hostname is not resolvable from the frontend app.
// Their public names share the same Container Apps environment suffix, so map
// the public frontend hostname to its paired public backend hostname.
const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '');

function getHostedApiBase() {
  if (typeof window === 'undefined') return '';
  const { hostname, protocol } = window.location;
  if (!hostname.startsWith('reposage-frontend.')) return '';
  return `${protocol}//${hostname.replace(/^reposage-frontend\./, 'reposage-backend.')}`;
}

export const API_BASE = configuredApiBase || getHostedApiBase();
