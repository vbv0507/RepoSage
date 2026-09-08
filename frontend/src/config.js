// Base API URL: In development this is empty (using Vite proxy),
// In production it points to the Azure Container Apps backend.
export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
