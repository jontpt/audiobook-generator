// ─── Global Types ───────────────────────────────────────────────────────────

export type ProcessingStatus =
  | 'pending' | 'extracting' | 'analyzing'
  | 'synthesizing' | 'mixing' | 'completed' | 'failed';

export type Gender = 'male' | 'female' | 'neutral';
export type EmotionTag =
  | 'neutral' | 'happy' | 'sad' | 'suspense'
  | 'dramatic' | 'romantic' | 'action' | 'mysterious' | 'peaceful';
export type SegmentType = 'narration' | 'dialogue';
export type ExportFormat = 'mp3' | 'm4b' | 'wav';

export interface User {
  id: string;
  email: string;
  username: string;
  created_at: string;
  is_active: boolean;
}

export interface ApiKey {
  id: string;
  service: string;        // 'elevenlabs' | 'mubert' | 'soundraw' | 'jamendo'
  label: string;
  key_preview: string;    // "sk-...ab12"
  is_valid: boolean | null;
  created_at: string;
}

export interface SfxLibraryInventory {
  success: boolean;
  root: string;
  total_files: number;
  categories: Record<string, { count: number; files: string[] }>;
}

export interface SfxLibraryUploadResult {
  success: boolean;
  message: string;
  import_report: {
    imported_count: number;
    imported_by_category: Record<string, number>;
    skipped_non_audio: number;
    skipped_too_large: number;
    skipped_bad_entries: number;
  };
  inventory: {
    root: string;
    total_files: number;
    categories: Record<string, { count: number; files: string[] }>;
  };
}

export interface VoiceInfo {
  voice_id: string;
  name: string;
  description: string;
  gender: Gender;
  age_group: string;
  accent: string;
}

export interface Character {
  id: string;
  book_id: string;
  name: string;
  gender: Gender;
  age_group: string;
  accent: string;
  voice_id: string | null;
  voice_name?: string;
  voice_description?: string;
  traits: string[];
  appearance_count: number;
}

export interface Chapter {
  id: string;
  book_id: string;
  index: number;
  title: string;
  dominant_emotion: EmotionTag;
  audio_path?: string;
  duration_ms?: number;
  segment_count: number;
}

export interface TextSegment {
  id: string;
  book_id: string;
  chapter_index: number;
  paragraph_index: number;
  segment_type: SegmentType;
  speaker: string | null;
  text: string;
  emotion: EmotionTag;
  audio_path?: string;
  duration_ms?: number;
}

export type MusicProvider = 'auto' | 'mubert' | 'soundraw' | 'jamendo';
export type MusicStylePreset =
  | 'auto'
  | 'cinematic'
  | 'ambient'
  | 'orchestral'
  | 'piano'
  | 'electronic';

export interface Book {
  id: string;
  title: string;
  author: string;
  status_reason?: string;
  draft_characters?: Character[];
  character_voice_candidates?: Record<string, string[]>;
  radio_cues?: RadioCue[];
  radio_cue_counts?: Record<string, number>;
  file_type?: string;
  status: ProcessingStatus;
  progress: number;
  error_message?: string;
  chapter_count: number;
  character_count: number;
  segment_count: number;
  total_words: number;
  export_path?: string;
  parent_book_id?: string | null;
  root_book_id?: string | null;
  revision_number?: number;
  created_at: string;
  updated_at: string;
  characters?: Character[];
  chapters?: Chapter[];
  revisions?: BookRevisionSummary[];
}

export interface BookRevisionSummary {
  id: string;
  title: string;
  author: string;
  status: ProcessingStatus;
  progress: number;
  revision_number: number;
  parent_book_id?: string | null;
  root_book_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BookRevisionCreateResponse {
  success: boolean;
  message: string;
  book_id: string;
  root_book_id: string;
  parent_book_id?: string | null;
  revision_number: number;
  title: string;
  ws_url: string;
}

export interface RadioCue {
  type: 'scene' | 'ambience' | 'foley' | 'music';
  value: string;
  label: string;
  params: Record<string, string>;
  chapter_index: number;
  paragraph_index: number;
}

export interface RadioCueLintIssue {
  severity: 'error' | 'warning';
  code: string;
  message: string;
  hint: string;
  chapter_index: number;
  paragraph_index: number;
}

export interface ExportStatus {
  book_id: string;
  title: string;
  status: ProcessingStatus;
  progress: number;
  export?: {
    duration_str: string;
    file_size_mb: number;
    filename: string;
    download_url: string;
  };
  error_message?: string;
}

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  password: string;
}
