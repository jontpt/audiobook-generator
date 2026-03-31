import apiClient from './client';
import type { ApiKey } from '../types';

export const settingsApi = {
  // ── API Keys ───────────────────────────────────────────────────────────────
  getApiKeys: async (): Promise<ApiKey[]> => {
    const res = await apiClient.get('/settings/api-keys');
    return res.data;
  },

  addApiKey: async (service: string, label: string, key: string): Promise<ApiKey> => {
    const res = await apiClient.post('/settings/api-keys', { service, label, key });
    return res.data;
  },

  deleteApiKey: async (keyId: string) => {
    const res = await apiClient.delete(`/settings/api-keys/${keyId}`);
    return res.data;
  },

  validateApiKey: async (keyId: string) => {
    const res = await apiClient.post(`/settings/api-keys/${keyId}/validate`);
    return res.data;
  },

  // ── User profile ──────────────────────────────────────────────────────────
  updateProfile: async (data: { username?: string; email?: string }) => {
    const res = await apiClient.patch('/settings/profile', data);
    return res.data;
  },
};
