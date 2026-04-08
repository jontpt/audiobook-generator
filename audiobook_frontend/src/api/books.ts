import apiClient from './client';
import type {
  Book,
  TextSegment,
  Character,
  MusicProvider,
  MusicStylePreset,
  RadioCue,
  RadioCueLintIssue,
} from '../types';

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
    musicVolumeDb: number = -18.0,   // ← NEW: dB value, range -30 to -6
    musicProvider: MusicProvider = 'auto',
    musicStyle: MusicStylePreset = 'auto',
    voiceAssignments: { character_name: string; voice_id: string }[] = [],
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('author', author);
    form.append('add_music', String(addMusic));
    form.append('export_format', exportFormat);
    form.append('music_volume_db', String(musicVolumeDb));   // ← NEW
    form.append('music_provider', musicProvider);
    form.append('music_style', musicStyle);
    if (voiceAssignments.length > 0) {
      form.append('voice_assignments_json', JSON.stringify(voiceAssignments));
    }
    const res = await apiClient.post('/books/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total));
      },
    });
    return res.data;
  },

  parseCharacters: async (
    file: File,
    title: string,
    author: string,
  ): Promise<{ characters: Character[]; suggestions_count: number }> => {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('author', author);
    const res = await apiClient.post('/books/parse-characters', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  previewRadioCues: async (
    file: File,
  ): Promise<{
    cues: RadioCue[];
    cue_counts: Record<string, number>;
    lint_issues: RadioCueLintIssue[];
    lint_counts: Record<string, number>;
    chapter_count: number;
  }> => {
    const form = new FormData();
    form.append('file', file);
    const res = await apiClient.post('/books/preview-radio-cues', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  startWithVoiceAssignments: async (
    file: File,
    title: string,
    author: string,
    assignments: { character_name: string; voice_id: string }[],
    addMusic: boolean = false,
    exportFormat: string = 'mp3',
    musicVolumeDb: number = -18.0,
    musicProvider: MusicProvider = 'auto',
    musicStyle: MusicStylePreset = 'auto',
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('author', author);
    form.append('add_music', String(addMusic));
    form.append('export_format', exportFormat);
    form.append('music_volume_db', String(musicVolumeDb));
    form.append('music_provider', musicProvider);
    form.append('music_style', musicStyle);
    form.append('voice_assignments_json', JSON.stringify(assignments));
    const res = await apiClient.post('/books/start-with-voices', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  delete: async (id: string) => {
    const res = await apiClient.delete(`/books/${id}`);
    return res.data;
  },

  reExport: async (
    id: string,
    format: string = 'mp3',
    addMusic: boolean = false,
    musicVolumeDb: number = -18.0,   // ← NEW
    musicProvider: MusicProvider = 'auto',
    musicStyle: MusicStylePreset = 'auto',
  ) => {
    const res = await apiClient.post(`/export/${id}`, null, {
      params: {
        export_format: format,
        add_music: addMusic,
        music_volume_db: musicVolumeDb,
        music_provider: musicProvider,
        music_style: musicStyle,
      },
    });
    return res.data;
  },

  getExportStatus: async (id: string) => {
    const res = await apiClient.get(`/export/${id}/status`);
    return res.data;
  },

  downloadUrl: (id: string) => `/api/v1/export/${id}/download`,
};
