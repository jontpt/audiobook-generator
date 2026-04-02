import axios from 'axios';

// In production (served by FastAPI), the API is at /api/v1
// In development (Vite proxy), it's also proxied to /api/v1
const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach JWT token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 — redirect to login
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;

// WebSocket helper — works in both dev and production
export function createProgressWebSocket(bookId: string): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  // In dev, Vite proxies /api → localhost:8000
  return new WebSocket(`${protocol}//${host}/api/v1/books/${bookId}/ws`);
}
