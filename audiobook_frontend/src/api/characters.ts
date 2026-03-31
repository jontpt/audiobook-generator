import apiClient from './client';
import type { Character, VoiceInfo } from '../types';

interface CharacterUpdate {
  gender?: string;
  age_group?: string;
  accent?: string;
  voice_id?: string;
  traits?: string[];
}

export const charactersApi = {
  list: async (bookId: string): Promise<Character[]> => {
    const res = await apiClient.get(`/books/${bookId}/characters`);
    return res.data;
  },

  update: async (bookId: string, charId: string, updates: CharacterUpdate) => {
    const res = await apiClient.patch(`/books/${bookId}/characters/${charId}`, updates);
    return res.data;
  },

  bulkAssignVoices: async (bookId: string, assignments: { character_name: string; voice_id: string }[]) => {
    const res = await apiClient.post(`/books/${bookId}/characters/assign-voices`, assignments);
    return res.data;
  },

  previewVoice: async (bookId: string, voiceId: string, text?: string) => {
    const res = await apiClient.post(`/books/${bookId}/characters/preview-voice`, null, {
      params: { voice_id: voiceId, text: text ?? 'Hello! I am a character in this story.' },
    });
    return res.data;
  },
};

export const voicesApi = {
  list: async (gender?: string, accent?: string): Promise<VoiceInfo[]> => {
    const res = await apiClient.get('/voices', { params: { gender, accent } });
    return res.data;
  },

  get: async (voiceId: string): Promise<VoiceInfo> => {
    const res = await apiClient.get(`/voices/${voiceId}`);
    return res.data;
  },
};
