import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ArrowLeft, BookOpen, Mic2, CheckCircle2, AlertCircle, 
  Download, RefreshCw, Users, FileText, Clock, Layers, Wifi, WifiOff, RefreshCcw,
} from 'lucide-react';
import { booksApi } from '../api/books';
import { Badge } from '../components/UI/Badge';
import { Button } from '../components/UI/Button';
import { useBookProgress } from '../hooks/useBookProgress';
import toast from 'react-hot-toast';

const STEP_LABELS: Record<string, string> = {
  pending:      'Waiting to start…',
  extracting:   'Extracting text from file…',
  analyzing:    'Analysing structure & characters…',
  synthesizing: 'Generating voices with TTS…',
  mixing:       'Assembling final audio…',
  completed:    'Audiobook ready! 🎉',
  failed:       'Processing failed',
};

const PIPELINE_STEPS = [
  { key: 'extracting',   label: 'Extract',    icon: '🔍' },
  { key: 'analyzing',    label: 'Analyse',    icon: '🧠' },
  { key: 'synthesizing', label: 'Synthesise', icon: '🎙️' },
  { key: 'mixing',       label: 'Mix',        icon: '🎵' },
  { key: 'completed',    label: 'Done',       icon: '✅' },
];
const STEP_ORDER = PIPELINE_STEPS.map(s => s.key);

function stepIndex(status: string) {
  const i = STEP_ORDER.indexOf(status);
  return i === -1 ? 0 : i;
}

const TERMINAL = ['completed', 'failed'] as const;
const isTerminal = (s?: string) => !!s && (TERMINAL as readonly string[]).includes(s);

export const BookDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [exporting, setExporting] = useState(false);

  // REST — poll every 3 s while not terminal, stop once done
  const { data: book, isLoading } = useQuery({
    queryKey:  ['book', id],
    queryFn:   () => booksApi.get(id!),
    enabled:   !!id,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return isTerminal(s) ? false : 3_000;
    },
  });

  // WS with auto-reconnect + REST fallback
  const ws = useBookProgress(id, book?.status ?? 'pending');

  // Only trust WS status after it has actually sent a message.
  // Before that, show the REST cache value so we never regress to stale "pending".
  const status   = ws.wsMessageReceived ? ws.status   : (book?.status   ?? 'pending');
  const progress = ws.wsMessageReceived ? ws.progress : (book?.progress ?? 0);
  const message  = ws.message || STEP_LABELS[status] || '';

  // Invalidate REST cache when WS signals completion / failure
  React.useEffect(() => {
    if (ws.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['book', id] });
      queryClient.invalidateQueries({ queryKey: ['export', id] });
      toast.success('Audiobook ready!');
    }
    if (ws.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['book', id] });
      toast.error('Processing failed');
    }
  }, [ws.status, id, queryClient]);

  const { data: exportStatus } = useQuery({
    queryKey: ['export', id],
    queryFn:  () => booksApi.getExportStatus(id!),
    enabled:  !!id && status === 'completed',
  });

  const handleReExport = async () => {
    if (!id) return;
    setExporting(true);
    try {
      await booksApi.reExport(id);
      queryClient.invalidateQueries({ queryKey: ['book', id] });
      toast.success('Re-export started');
    } catch { toast.error('Re-export failed'); }
    finally { setExporting(false); }
  };

  if (isLoading) return (
    <div className="flex items-center justify-center py-24">
      <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
  if (!book) return <div className="text-dark-400 text-center py-20">Book not found.</div>;

  const isProcessing = !['completed', 'failed', 'pending'].includes(status);
  const progressPct  = Math.round(progress * 100);
  const currentStep  = stepIndex(status);

  // Three-state connection badge
  const connLabel = ws.connected ? 'Live' : ws.usingFallback ? 'Polling' : 'Reconnecting';
  const ConnIcon  = ws.connected ? Wifi   : ws.usingFallback ? WifiOff   : RefreshCcw;
  const connCls   = ws.connected
    ? 'bg-green-500/10 text-green-400'
    : ws.usingFallback
      ? 'bg-dark-700 text-dark-400'
      : 'bg-amber-500/10 text-amber-400';

  return (
    <div>
      <Link to="/dashboard" className="inline-flex items-center gap-2 text-dark-400 hover:text-white transition-colors mb-6 text-sm">
        <ArrowLeft size={16} /> Back to Dashboard
      </Link>

      <div className="flex items-start justify-between gap-4 mb-8">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-brand/10 border border-brand-500/20 flex items-center justify-center">
            <BookOpen size={24} className="text-brand-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">{book.title}</h1>
            <p className="text-dark-400">{book.author}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isProcessing && (
            <div className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full transition-all ${connCls}`}>
              <ConnIcon size={12} />
              {connLabel}
            </div>
          )}
          <Badge type="status" value={status} />
          {status === 'completed' && (
            <>
              <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />}
                onClick={handleReExport} loading={exporting}>Re-export</Button>
              <a href={booksApi.downloadUrl(id!)} download>
                <Button variant="primary" size="sm" icon={<Download size={14} />}>Download MP3</Button>
              </a>
            </>
          )}
        </div>
      </div>

      <AnimatePresence>
        {(isProcessing || status === 'failed') && (
          <motion.div
            className="bg-dark-800/60 border border-dark-700 rounded-2xl p-6 mb-6"
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
          >
            <div className="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
              {PIPELINE_STEPS.map((step, i) => (
                <React.Fragment key={step.key}>
                  <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all
                    ${i < currentStep  ? 'bg-green-500/15 text-green-400 border border-green-500/20' :
                      i === currentStep ? 'bg-brand-500/20 text-brand-300 border border-brand-500/30 shadow-glow-sm' :
                                          'bg-dark-700/50 text-dark-500 border border-dark-700'}`}>
                    <span>{step.icon}</span><span>{step.label}</span>
                  </div>
                  {i < PIPELINE_STEPS.length - 1 && (
                    <div className={`h-px w-4 flex-shrink-0 ${i < currentStep ? 'bg-green-500/40' : 'bg-dark-700'}`} />
                  )}
                </React.Fragment>
              ))}
            </div>

            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {status === 'failed'
                  ? <AlertCircle size={16} className="text-red-400" />
                  : <div className="w-4 h-4 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />}
                <span className="font-medium text-white text-sm">{message}</span>
              </div>
              <span className="text-brand-400 font-bold text-sm">{progressPct}%</span>
            </div>
            <div className="h-2.5 bg-dark-700 rounded-full overflow-hidden">
              <motion.div className="h-full bg-gradient-brand rounded-full"
                animate={{ width: `${progressPct}%` }} transition={{ duration: 0.5 }} />
            </div>
            {ws.error && <p className="text-red-400 text-sm mt-3 font-mono">{ws.error}</p>}
            {book.error_message && !ws.error && (
              <p className="text-red-400 text-sm mt-3 font-mono">{book.error_message}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {status === 'completed' && exportStatus?.export && (
        <motion.div className="bg-green-500/10 border border-green-500/20 rounded-2xl p-6 mb-6"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <div className="flex items-center gap-3 mb-3">
            <CheckCircle2 size={20} className="text-green-400" />
            <h3 className="font-semibold text-white">Audiobook Ready</h3>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div><p className="text-dark-400">Duration</p><p className="text-white font-medium">{exportStatus.export.duration_str || '—'}</p></div>
            <div><p className="text-dark-400">File Size</p><p className="text-white font-medium">{exportStatus.export.file_size_mb} MB</p></div>
            <div><p className="text-dark-400">Format</p><p className="text-white font-medium font-mono">{exportStatus.export.filename?.split('.').pop()?.toUpperCase()}</p></div>
          </div>
        </motion.div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { icon: <Layers   size={16} className="text-brand-400"   />, label: 'Chapters',   value: book.chapter_count },
          { icon: <Users    size={16} className="text-accent-teal" />, label: 'Characters', value: book.character_count },
          { icon: <FileText size={16} className="text-accent-amber"/>, label: 'Segments',   value: book.segment_count },
          { icon: <Clock    size={16} className="text-purple-400"  />, label: 'Words',      value: book.total_words?.toLocaleString() },
        ].map(({ icon, label, value }) => (
          <div key={label} className="bg-dark-800/60 border border-dark-700 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">{icon}<span className="text-xs text-dark-400">{label}</span></div>
            <p className="text-xl font-bold text-white">{value || '—'}</p>
          </div>
        ))}
      </div>

      {book.characters && book.characters.length > 0 && (
        <div className="bg-dark-800/40 border border-dark-700 rounded-2xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <Mic2 size={16} className="text-brand-400" /> Characters & Voices
            </h3>
            <Link to={`/books/${id}/characters`} className="text-sm text-brand-400 hover:text-brand-300 transition-colors">
              Edit voices →
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {book.characters.slice(0, 6).map(char => (
              <div key={char.id} className="flex items-center gap-2 bg-dark-900/50 rounded-xl p-3">
                <div className="w-8 h-8 rounded-full bg-gradient-brand/20 border border-brand-500/20 flex items-center justify-center text-sm font-bold text-brand-300">
                  {char.name[0].toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white truncate">{char.name}</p>
                  <p className="text-xs text-dark-400 truncate">{char.voice_name ?? 'Auto assigned'}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {book.chapters && book.chapters.length > 0 && (
        <div className="bg-dark-800/40 border border-dark-700 rounded-2xl p-5">
          <h3 className="font-semibold text-white mb-4 flex items-center gap-2">
            <BookOpen size={16} className="text-brand-400" /> Chapters
          </h3>
          <div className="space-y-2">
            {book.chapters.sort((a, b) => a.index - b.index).map(ch => (
              <div key={ch.id} className="flex items-center gap-3 py-2.5 px-3 rounded-xl bg-dark-900/40 hover:bg-dark-900/60 transition-colors">
                <span className="text-xs font-mono text-dark-500 w-6">{ch.index + 1}</span>
                <span className="flex-1 text-sm text-white truncate">{ch.title}</span>
                <Badge type="emotion" value={ch.dominant_emotion} />
                <span className="text-xs text-dark-500">{ch.segment_count} segs</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
