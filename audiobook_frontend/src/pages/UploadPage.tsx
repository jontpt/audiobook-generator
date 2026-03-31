import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, FileText, X, CheckCircle, AlertCircle, ArrowRight } from 'lucide-react';
import { booksApi } from '../api/books';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';

const ACCEPT = { 'application/pdf': ['.pdf'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'], 'application/epub+zip': ['.epub'], 'text/plain': ['.txt'] };
const FORMAT_ICONS: Record<string, string> = { pdf: '📄', docx: '📝', epub: '📚', txt: '📃' };

export const UploadPage: React.FC = () => {
  const [file, setFile]     = useState<File | null>(null);
  const [title, setTitle]   = useState('');
  const [author, setAuthor] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const navigate     = useNavigate();
  const queryClient  = useQueryClient();

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) {
      setFile(accepted[0]);
      const base = accepted[0].name.replace(/\.[^.]+$/, '').replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
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
      const result = await booksApi.upload(file, title, author || 'Unknown', pct => setUploadPct(pct));
      queryClient.invalidateQueries({ queryKey: ['books'] });
      toast.success('Upload successful! Processing has started.');
      navigate(`/books/${result.book_id}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Upload failed. Please try again.');
      setUploading(false);
    }
  };

  const ext = file?.name.split('.').pop()?.toLowerCase() ?? '';

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Create New Audiobook</h1>
        <p className="text-dark-400 mt-1">Upload your book and let AI do the rest</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Dropzone */}
        <div {...getRootProps()} className={`relative rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer
          ${isDragActive ? 'border-brand-400 bg-brand-500/10' : 'border-dark-700 bg-dark-800/40 hover:border-dark-600 hover:bg-dark-800/60'}
          ${file ? 'border-green-500/50 bg-green-500/5' : ''}`}
        >
          <input {...getInputProps()} />
          <div className="flex flex-col items-center justify-center py-14 px-6 text-center">
            <AnimatePresence mode="wait">
              {file ? (
                <motion.div key="file" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
                  className="flex flex-col items-center">
                  <div className="text-5xl mb-3">{FORMAT_ICONS[ext] ?? '📄'}</div>
                  <div className="flex items-center gap-2 mb-1">
                    <CheckCircle size={16} className="text-green-400" />
                    <span className="font-semibold text-white">{file.name}</span>
                  </div>
                  <span className="text-sm text-dark-400">
                    {(file.size / 1024 / 1024).toFixed(2)} MB · {ext.toUpperCase()}
                  </span>
                  <button type="button" onClick={(e) => { e.stopPropagation(); setFile(null); }}
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

        {/* Metadata */}
        <div className="grid grid-cols-2 gap-4">
          <Input label="Book Title" placeholder="The Great Gatsby"
            value={title} onChange={e => setTitle(e.target.value)} required />
          <Input label="Author" placeholder="F. Scott Fitzgerald"
            value={author} onChange={e => setAuthor(e.target.value)} />
        </div>

        {/* Upload progress */}
        {uploading && (
          <div>
            <div className="flex justify-between text-xs text-dark-400 mb-1">
              <span>Uploading…</span><span>{uploadPct}%</span>
            </div>
            <div className="h-2 bg-dark-700 rounded-full overflow-hidden">
              <motion.div className="h-full bg-gradient-brand rounded-full"
                animate={{ width: `${uploadPct}%` }} transition={{ duration: 0.3 }} />
            </div>
          </div>
        )}

        <Button type="submit" variant="primary" size="lg" className="w-full"
          disabled={!file || !title} loading={uploading}
          iconRight={<ArrowRight size={16} />}>
          Start Processing
        </Button>
      </form>

      {/* How it works */}
      <div className="mt-10 p-5 bg-dark-800/40 border border-dark-700 rounded-2xl">
        <h3 className="text-sm font-semibold text-white mb-4">How it works</h3>
        <div className="space-y-3">
          {[
            ['🔍', 'Extract', 'Text extracted and structured into chapters'],
            ['🧠', 'Analyze', 'NLP detects dialogue, characters & emotions'],
            ['🎙️', 'Synthesize', 'ElevenLabs generates distinct voices per character'],
            ['🎵', 'Mix', 'Audio assembled with optional background music'],
          ].map(([icon, step, desc]) => (
            <div key={step} className="flex items-start gap-3">
              <span className="text-lg leading-none mt-0.5">{icon}</span>
              <div>
                <span className="text-xs font-semibold text-brand-400 uppercase tracking-wider">{step} · </span>
                <span className="text-xs text-dark-400">{desc}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
