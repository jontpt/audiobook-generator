import apiClient from './client';
import type { Book, TextSegment } from '../types';

export const booksApi = {
  list: async (): Promise<Book[]> => {
    const res = await apiClient.get('/books');
    return res.data;
  },

  get: async (id: string): Promise<Book> => {
    const res = await apiClient.get(`/books/${id}`);
    return res.data;
  },

  getProgress: async (id: string) => {
    const res = await apiClient.get(`/books/${id}/progress`);
    return res.data;
  },

  getSegments: async (id: string, chapterIndex?: number): Promise<TextSegment[]> => {
    const params = chapterIndex !== undefined ? { chapter_index: chapterIndex } : {};
    const res = await apiClient.get(`/books/${id}/segments`, { params });
    return res.data;
  },

  upload: async (
    file: File,
    title: string,
    author: string,
    onProgress?: (pct: number) => void,
    addMusic: boolean = false,
    exportFormat: string = 'mp3',
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('author', author);
    form.append('add_music', String(addMusic));
    form.append('export_format', exportFormat);
    const res = await apiClient.post('/books/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total));
      },
    });
    return res.data;
  },

  delete: async (id: string) => {
    const res = await apiClient.delete(`/books/${id}`);
    return res.data;
  },

  reExport: async (id: string, format: string = 'mp3', addMusic: boolean = false) => {
    const res = await apiClient.post(`/export/${id}`, null, {
      params: { export_format: format, add_music: addMusic },
    });
    return res.data;
  },

  getExportStatus: async (id: string) => {
    const res = await apiClient.get(`/export/${id}/status`);
    return res.data;
  },

  downloadUrl: (id: string) => `/api/v1/export/${id}/download`,
};
