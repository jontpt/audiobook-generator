import apiClient from './client';
import type { AuthTokens, User, LoginRequest, RegisterRequest } from '../types';
import axios from 'axios';

export const authApi = {
  login: async (data: LoginRequest): Promise<AuthTokens> => {
    // OAuth2 form-encoded login
    const form = new FormData();
    form.append('username', data.username);
    form.append('password', data.password);
    const res = await axios.post('/api/v1/auth/login', form);
    return res.data;
  },

  register: async (data: RegisterRequest): Promise<User> => {
    const res = await apiClient.post('/auth/register', data);
    return res.data;
  },

  me: async (): Promise<User> => {
    const res = await apiClient.get('/auth/me');
    return res.data;
  },

  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
  },

  changePassword: async (current: string, newPass: string) => {
    const res = await apiClient.post('/auth/change-password', {
      current_password: current,
      new_password: newPass,
    });
    return res.data;
  },
};
