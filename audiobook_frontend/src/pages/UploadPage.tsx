import React, { useState, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, X, CheckCircle, AlertCircle, ArrowRight,
  Music, Settings, ChevronDown, ChevronUp, Volume1, Volume2, VolumeX,
} from 'lucide-react';
import { booksApi } from '../api/books';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

const ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/epub+zip': ['.epub'],
  'text/plain': ['.txt'],
};
const FORMAT_ICONS: Record<string, string> = { pdf: '📄', docx: '📝', epub: '📚', txt: '📃' };

// ── Volume helpers ────────────────────────────────────────────────────────────
// Slider: 0–100   ↔   dB: –30 to –6
// Default –18 dB  →  slider 50
const SLIDER_MIN_DB = -30;
const SLIDER_MAX_DB = -6;
const DB_RANGE      = SLIDER_MAX_DB - SLIDER_MIN_DB; // 24

const sliderToDb  = (v: number): number => SLIDER_MIN_DB + (v / 100) * DB_RANGE;
const dbToSlider  = (db: number): number => Math.round(((db - SLIDER_MIN_DB) / DB_RANGE) * 100);

const volumeLabel = (v: number): string => {
  if (v <= 20)  return 'Subtle';
  if (v <= 45)  return 'Soft';
  if (v <= 60)  return 'Moderate';
  if (v <= 80)  return 'Present';
  return 'Loud';
};

const VolumeIcon = ({ v }: { v: number }) => {
  if (v === 0)  return <VolumeX  size={14} className="text-dark-400" />;
  if (v <= 50)  return <Volume1  size={14} className="text-accent-teal" />;
  return              <Volume2  size={14} className="text-accent-teal" />;
};

// ─────────────────────────────────────────────────────────────────────────────

export const UploadPage: React.FC = () => {
  const [file, setFile]           = useState<File | null>(null);
  const [title, setTitle]         = useState('');
  const [author, setAuthor]       = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);

  // ── Production options ───────────────────────────────────────────────────
  const [addMusic, setAddMusic]         = useState(false);
  const [musicSlider, setMusicSlider]   = useState(dbToSlider(-18)); // 50
  const [exportFormat, setExportFormat] = useState<'mp3' | 'm4b'>('mp3');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const navigate    = useNavigate();
  const queryClient = useQueryClient();

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) {
      setFile(accepted[0]);
      const base = accepted[0].name
        .replace(/\.[^.]+$/, '')
        .replace(/[_-]/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
      if (!title) setTitle(base);
    }
  }, [title]);

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop, accept: ACCEPT, maxSize: 50 * 1024 * 1024, maxFiles: 1,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    try {
      const result = await booksApi.upload(
        file,
        title,
        author || 'Unknown',
        pct => setUploadPct(pct),
        addMusic,
        exportFormat,
        sliderToDb(musicSlider),   // convert slider → dB before sending
      );
      queryClient.invalidateQueries({ queryKey: ['books'] });
      toast.success('Upload successful! Processing has started.');
      navigate(`/books/${result.book_id}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Upload failed. Please try again.');
      setUploading(false);
    }
  };

  const ext = file?.name.split('.').pop()?.toLowerCase() ?? '';

  // Badge shown in collapsed header when non-default options are active
  const optionBadges = [
    addMusic && `🎵 ${volumeLabel(musicSlider)}`,
    exportFormat === 'm4b' && 'M4B',
  ].filter(Boolean).join(' · ');

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Create New Audiobook</h1>
        <p className="text-dark-400 mt-1">Upload your book and let AI do the rest</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">

        {/* ── Dropzone ──────────────────────────────────────────────────── */}
        <div
          {...getRootProps()}
          className={`relative rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer
            ${isDragActive
              ? 'border-brand-400 bg-brand-500/10'
              : 'border-dark-700 bg-dark-800/40 hover:border-dark-600 hover:bg-dark-800/60'}
            ${file ? 'border-green-500/50 bg-green-500/5' : ''}`}
        >
          <input {...getInputProps()} />
          <div className="flex flex-col items-center justify-center py-14 px-6 text-center">
            <AnimatePresence mode="wait">
              {file ? (
                <motion.div
                  key="file"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex flex-col items-center">
                  <div className="text-5xl mb-3">{FORMAT_ICONS[ext] ?? '📄'}</div>
                  <div className="flex items-center gap-2 mb-1">
                    <CheckCircle size={16} className="text-green-400" />
                    <span className="font-semibold text-white">{file.name}</span>
                  </div>
                  <span className="text-sm text-dark-400">
                    {(file.size / 1024 / 1024).toFixed(2)} MB · {ext.toUpperCase()}
                  </span>
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); setFile(null); }}
                    className="mt-3 text-xs text-dark-400 hover:text-red-400 flex items-center gap-1 transition-colors">
                    <X size={12} /> Remove file
                  </button>
                </motion.div>
              ) : (
                <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <div className={`w-14 h-14 rounded-2xl border flex items-center justify-center mx-auto mb-4 transition-all
                    ${isDragActive ? 'bg-brand-500/20 border-brand-500/30' : 'bg-dark-700 border-dark-600'}`}>
                    <Upload size={24} className={isDragActive ? 'text-brand-400' : 'text-dark-400'} />
                  </div>
                  <p className="text-white font-semibold mb-1">
                    {isDragActive ? 'Drop it here!' : 'Drop your book file here'}
                  </p>
                  <p className="text-sm text-dark-400 mb-3">or click to browse</p>
                  <div className="flex items-center gap-2">
                    {['PDF', 'DOCX', 'ePub', 'TXT'].map(f => (
                      <span key={f} className="px-2 py-0.5 rounded-md bg-dark-700 text-xs text-dark-300 font-mono">{f}</span>
                    ))}
                  </div>
                  <p className="text-xs text-dark-500 mt-2">Max 50 MB</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {fileRejections.length > 0 && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle size={14} />
            {fileRejections[0]?.errors[0]?.message ?? 'Invalid file'}
          </div>
        )}

        {/* ── Metadata ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Book Title"
            placeholder="The Great Gatsby"
            value={title}
            onChange={e => setTitle(e.target.value)}
            required
          />
          <Input
            label="Author"
            placeholder="F. Scott Fitzgerald"
            value={author}
            onChange={e => setAuthor(e.target.value)}
          />
        </div>

        {/* ── Production options ─────────────────────────────────────────── */}
        <div className="bg-dark-800/60 border border-dark-700 rounded-2xl overflow-hidden">

          {/* Collapsed header */}
          <button
            type="button"
            onClick={() => setShowAdvanced(v => !v)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-dark-700/40 transition-colors">
            <div className="flex items-center gap-2 text-sm font-medium text-dark-200">
              <Settings size={14} className="text-brand-400" />
              Production Options
              {optionBadges && (
                <span className="ml-1 px-1.5 py-0.5 rounded-md bg-brand-500/20 text-brand-300 text-xs">
                  {optionBadges}
                </span>
              )}
            </div>
            {showAdvanced
              ? <ChevronUp size={14} className="text-dark-400" />
              : <ChevronDown size={14} className="text-dark-400" />}
          </button>

          <AnimatePresence>
            {showAdvanced && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden">
                <div className="px-4 pb-4 space-y-5 border-t border-dark-700 pt-4">

                  {/* ── Background Music toggle ──────────────────────────── */}
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-lg bg-accent-teal/10 border border-accent-teal/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <Music size={14} className="text-accent-teal" />
                        </div>
                        <div>
                          <p className="text-sm font-medium text-white">Background Music</p>
                          <p className="text-xs text-dark-400 mt-0.5">
                            AI-generated ambient music matched to each chapter's emotion,
                            ducked under the narration.
                          </p>
                          <p className="text-xs text-dark-500 mt-1">
                            Requires a{' '}
                            <Link to="/settings" className="text-brand-400 hover:underline">
                              Mubert or Soundraw API key
                            </Link>{' '}
                            in Settings.
                          </p>
                        </div>
                      </div>

                      {/* Toggle switch */}
                      <button
                        type="button"
                        onClick={() => setAddMusic(v => !v)}
                        className={`relative flex-shrink-0 w-11 h-6 rounded-full transition-colors duration-200
                          focus:outline-none focus:ring-2 focus:ring-accent-teal/40
                          ${addMusic ? 'bg-accent-teal' : 'bg-dark-600'}`}>
                        <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow
                          transition-transform duration-200
                          ${addMusic ? 'translate-x-5' : 'translate-x-0'}`} />
                      </button>
                    </div>

                    {/* ── Volume slider — only visible when music is on ──── */}
                    <AnimatePresence>
                      {addMusic && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.18 }}
                          className="overflow-hidden">
                          <div className="ml-11 bg-dark-900/50 border border-dark-700 rounded-xl px-4 py-3 space-y-2">

                            {/* Label row */}
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-1.5">
                                <VolumeIcon v={musicSlider} />
                                <span className="text-xs font-medium text-white">Music Volume</span>
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold text-accent-teal">
                                  {volumeLabel(musicSlider)}
                                </span>
                                <span className="text-xs text-dark-500 font-mono">
                                  {sliderToDb(musicSlider).toFixed(0)} dB
                                </span>
                              </div>
                            </div>

                            {/* Slider track */}
                            <div className="relative">
                              <input
                                type="range"
                                min={0}
                                max={100}
                                step={1}
                                value={musicSlider}
                                onChange={e => setMusicSlider(Number(e.target.value))}
                                className="
                                  w-full h-1.5 rounded-full appearance-none cursor-pointer
                                  bg-dark-700
                                  [&::-webkit-slider-thumb]:appearance-none
                                  [&::-webkit-slider-thumb]:w-4
                                  [&::-webkit-slider-thumb]:h-4
                                  [&::-webkit-slider-thumb]:rounded-full
                                  [&::-webkit-slider-thumb]:bg-accent-teal
                                  [&::-webkit-slider-thumb]:shadow-md
                                  [&::-webkit-slider-thumb]:border-2
                                  [&::-webkit-slider-thumb]:border-dark-800
                                  [&::-webkit-slider-thumb]:transition-transform
                                  [&::-webkit-slider-thumb]:hover:scale-110
                                  [&::-moz-range-thumb]:w-4
                                  [&::-moz-range-thumb]:h-4
                                  [&::-moz-range-thumb]:rounded-full
                                  [&::-moz-range-thumb]:bg-accent-teal
                                  [&::-moz-range-thumb]:border-2
                                  [&::-moz-range-thumb]:border-dark-800
                                "
                                style={{
                                  background: `linear-gradient(to right, var(--color-accent-teal, #2dd4bf) ${musicSlider}%, rgb(55 65 81) ${musicSlider}%)`,
                                }}
                              />
                            </div>

                            {/* Scale labels */}
                            <div className="flex justify-between text-xs text-dark-500 px-0.5">
                              <span>Subtle</span>
                              <span>Moderate</span>
                              <span>Loud</span>
                            </div>

                            {/* Reset to default */}
                            {musicSlider !== dbToSlider(-18) && (
                              <button
                                type="button"
                                onClick={() => setMusicSlider(dbToSlider(-18))}
                                className="text-xs text-dark-500 hover:text-brand-400 transition-colors">
                                Reset to default
                              </button>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>

                  {/* ── Export Format ────────────────────────────────────── */}
                  <div>
                    <p className="text-sm font-medium text-white mb-2">Export Format</p>
                    <div className="grid grid-cols-2 gap-2">
                      {([
                        { value: 'mp3', label: 'MP3', desc: 'Universal · smaller file' },
                        { value: 'm4b', label: 'M4B', desc: 'Audiobook · chapter markers' },
                      ] as const).map(opt => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setExportFormat(opt.value)}
                          className={`flex flex-col items-start px-3 py-2.5 rounded-xl border text-left transition-all
                            ${exportFormat === opt.value
                              ? 'border-brand-500/60 bg-brand-500/10'
                              : 'border-dark-700 bg-dark-900/40 hover:border-dark-600'}`}>
                          <span className={`text-sm font-semibold
                            ${exportFormat === opt.value ? 'text-brand-300' : 'text-white'}`}>
                            {opt.label}
                          </span>
                          <span className="text-xs text-dark-400 mt-0.5">{opt.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ── Upload progress ────────────────────────────────────────────── */}
        {uploading && (
          <div>
            <div className="flex justify-between text-xs text-dark-400 mb-1">
              <span>Uploading…</span>
              <span>{uploadPct}%</span>
            </div>
            <div className="h-2 bg-dark-700 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-brand rounded-full"
                animate={{ width: `${uploadPct}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          </div>
        )}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          disabled={!file || !title}
          loading={uploading}
          iconRight={<ArrowRight size={16} />}>
          Start Processing
        </Button>
      </form>

      {/* ── How it works ───────────────────────────────────────────────────── */}
      <div className="mt-10 p-5 bg-dark-800/40 border border-dark-700 rounded-2xl">
        <h3 className="text-sm font-semibold text-white mb-4">How it works</h3>
        <div className="space-y-3">
          {[
            ['🔍', 'Extract',    'Text extracted and structured into chapters'],
            ['🧠', 'Analyze',    'NLP detects dialogue, characters & emotions'],
            ['🎙️', 'Synthesize', 'ElevenLabs generates distinct voices per character'],
            ['🎵', 'Mix',        addMusic
              ? `Audio assembled with ${volumeLabel(musicSlider).toLowerCase()} background music matched to chapter mood`
              : 'Audio assembled with optional background music'],
          ].map(([icon, step, desc]) => (
            <div key={step as string} className="flex items-start gap-3">
              <span className="text-lg leading-none mt-0.5">{icon}</span>
              <div>
                <span className={`text-xs font-semibold uppercase tracking-wider
                  ${step === 'Mix' && addMusic ? 'text-accent-teal' : 'text-brand-400'}`}>
                  {step} ·{' '}
                </span>
                <span className="text-xs text-dark-400">{desc}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
