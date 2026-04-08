import React, { useMemo, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
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
import type { BookRevisionSummary, BookRevisionDiffResponse } from '../types';

const MUSIC_STYLE_OPTIONS = [
  { value: 'auto', label: 'Auto', desc: 'Match chapter emotion' },
  { value: 'ambient', label: 'Ambient', desc: 'Soft neutral bed' },
  { value: 'cinematic', label: 'Cinematic', desc: 'Orchestral / dramatic' },
  { value: 'orchestral', label: 'Orchestral', desc: 'Strings / epic score' },
  { value: 'piano', label: 'Piano', desc: 'Warm organic texture' },
  { value: 'electronic', label: 'Electronic', desc: 'Synth / modern bed' },
];

const MUSIC_PROVIDER_OPTIONS = [
  { value: 'auto', label: 'Auto provider' },
  { value: 'mubert', label: 'Mubert' },
  { value: 'soundraw', label: 'Soundraw' },
  { value: 'jamendo', label: 'Jamendo' },
];

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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [exporting, setExporting] = useState(false);
  const [creatingRework, setCreatingRework] = useState(false);
  const [comparingRevisions, setComparingRevisions] = useState(false);
  const [showReExportOptions, setShowReExportOptions] = useState(false);
  const [selectedCompareRevisionId, setSelectedCompareRevisionId] = useState<string>('');
  const [revisionDiff, setRevisionDiff] = useState<BookRevisionDiffResponse | null>(null);
  const [revisionDiffError, setRevisionDiffError] = useState<string | null>(null);
  const [reExportAddMusic, setReExportAddMusic] = useState(false);
  const [reExportStyle, setReExportStyle] = useState<'auto' | 'ambient' | 'cinematic' | 'orchestral' | 'piano' | 'electronic'>('auto');
  const [reExportProvider, setReExportProvider] = useState<'auto' | 'mubert' | 'soundraw' | 'jamendo'>('auto');

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
      await booksApi.reExport(
        id,
        'mp3',
        reExportAddMusic,
        -18.0,
        reExportProvider,
        reExportStyle,
      );
      queryClient.invalidateQueries({ queryKey: ['book', id] });
      toast.success('Re-export started');
    } catch { toast.error('Re-export failed'); }
    finally { setExporting(false); }
  };

  const handleCreateRework = async () => {
    if (!id) return;
    setCreatingRework(true);
    try {
      const result = await booksApi.createReworkVersion(id);
      queryClient.invalidateQueries({ queryKey: ['books'] });
      queryClient.invalidateQueries({ queryKey: ['book', id] });
      toast.success(`Created ${result.title}`);
      navigate(`/books/${result.book_id}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to create rework version');
    } finally {
      setCreatingRework(false);
    }
  };

  const revisions = useMemo(
    () => (book?.revisions as BookRevisionSummary[] | undefined) ?? [],
    [book?.revisions],
  );

  const handleCompareRevisions = async () => {
    if (!id || !selectedCompareRevisionId) return;
    setComparingRevisions(true);
    setRevisionDiffError(null);
    try {
      const data = await booksApi.getRevisionDiff(id, selectedCompareRevisionId);
      setRevisionDiff(data);
      if (!data.diff.has_changes) {
        toast('No detected differences between these revisions.', { icon: 'ℹ️' });
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? 'Failed to compare revisions';
      setRevisionDiffError(msg);
      toast.error(msg);
    } finally {
      setComparingRevisions(false);
    }
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
              <Button
                variant="outline"
                size="sm"
                icon={<Layers size={14} />}
                onClick={handleCreateRework}
                loading={creatingRework}
              >
                Create Rework Version
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={() => setShowReExportOptions(v => !v)}
              >
                Re-export Options
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={handleReExport}
                loading={exporting}
              >
                Re-export
              </Button>
              <a href={booksApi.downloadUrl(id!)} download>
                <Button variant="primary" size="sm" icon={<Download size={14} />}>Download MP3</Button>
              </a>
            </>
          )}
        </div>
      </div>

      <AnimatePresence>
        {status === 'completed' && showReExportOptions && (
          <motion.div
            className="bg-dark-800/60 border border-dark-700 rounded-2xl p-4 mb-6"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
          >
            <div className="flex items-center justify-between gap-4 mb-3">
              <div>
                <p className="text-sm font-medium text-white">Re-export background music</p>
                <p className="text-xs text-dark-400">Apply music settings for the next export run.</p>
              </div>
              <button
                type="button"
                onClick={() => setReExportAddMusic(v => !v)}
                className={`relative flex-shrink-0 w-11 h-6 rounded-full transition-colors duration-200 ${
                  reExportAddMusic ? 'bg-accent-teal' : 'bg-dark-600'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform duration-200 ${
                    reExportAddMusic ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {reExportAddMusic && (
              <div className="grid md:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-dark-400 block mb-1">Style preset</label>
                  <select
                    value={reExportStyle}
                    onChange={(e) => setReExportStyle(e.target.value as any)}
                    className="w-full bg-dark-900 border border-dark-700 rounded-lg px-3 py-2 text-sm text-white"
                  >
                    {MUSIC_STYLE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label} — {opt.desc}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-dark-400 block mb-1">Provider</label>
                  <select
                    value={reExportProvider}
                    onChange={(e) => setReExportProvider(e.target.value as any)}
                    className="w-full bg-dark-900 border border-dark-700 rounded-lg px-3 py-2 text-sm text-white"
                  >
                    {MUSIC_PROVIDER_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

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

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        {[
          { icon: <Layers   size={16} className="text-purple-400"  />, label: 'Revision', value: `v${book.revision_number ?? 1}` },
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

      {book.revisions && book.revisions.length > 1 && (
        <div className="bg-dark-800/40 border border-dark-700 rounded-2xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <Layers size={16} className="text-brand-400" /> Revision Timeline
            </h3>
            <span className="text-xs text-dark-400">
              Root: {book.root_book_id?.slice(0, 8) ?? book.id.slice(0, 8)}
            </span>
          </div>
          <div className="space-y-2">
            {(book.revisions as BookRevisionSummary[]).map((rev) => {
              const isCurrent = rev.id === book.id;
              return (
                <button
                  key={rev.id}
                  type="button"
                  onClick={() => navigate(`/books/${rev.id}`)}
                  className={`w-full flex items-center gap-3 py-2.5 px-3 rounded-xl border text-left transition-colors ${
                    isCurrent
                      ? 'border-brand-500/40 bg-brand-500/10'
                      : 'border-dark-700 bg-dark-900/40 hover:bg-dark-900/60'
                  }`}
                >
                  <span className="text-xs font-mono text-dark-500 w-10">v{rev.revision_number}</span>
                  <span className="flex-1 text-sm text-white truncate">{rev.title}</span>
                  <Badge type="status" value={rev.status} />
                  <span className="text-xs text-dark-500">
                    {new Date(rev.created_at).toLocaleDateString()}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-4 pt-4 border-t border-dark-700">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[260px]">
                <label className="text-xs text-dark-400 block mb-1">Compare current revision with</label>
                <select
                  value={selectedCompareRevisionId}
                  onChange={(e) => {
                    setSelectedCompareRevisionId(e.target.value);
                    setRevisionDiff(null);
                    setRevisionDiffError(null);
                  }}
                  className="w-full bg-dark-900 border border-dark-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  <option value="">Select a revision…</option>
                  {revisions
                    .filter((rev) => rev.id !== book.id)
                    .map((rev) => (
                      <option key={rev.id} value={rev.id}>
                        v{rev.revision_number} — {rev.title}
                      </option>
                    ))}
                </select>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCompareRevisions}
                loading={comparingRevisions}
                disabled={!selectedCompareRevisionId}
              >
                Compare Revisions
              </Button>
            </div>

            {revisionDiffError && (
              <p className="text-xs text-red-400 mt-2">{revisionDiffError}</p>
            )}

            {revisionDiff && (
              <div className="mt-4 rounded-xl border border-dark-700 bg-dark-900/30 p-4 space-y-4">
                <div className="text-xs text-dark-400">
                  Base: <span className="text-dark-200 font-mono">v{revisionDiff.base.revision_number}</span> ·
                  Compare: <span className="text-dark-200 font-mono"> v{revisionDiff.compare.revision_number}</span>
                </div>

                <div>
                  <p className="text-xs uppercase tracking-wide text-dark-400 mb-2">Metrics Delta</p>
                  <div className="grid md:grid-cols-2 gap-2 text-xs">
                    {Object.entries(revisionDiff.diff.metrics).map(([k, m]) => (
                      <div key={k} className="rounded-lg border border-dark-700 bg-dark-800/40 px-3 py-2">
                        <div className="flex items-center justify-between">
                          <span className="text-dark-300">{k}</span>
                          <span className={m.delta === 0 ? 'text-dark-500' : m.delta > 0 ? 'text-green-400' : 'text-amber-300'}>
                            {m.delta > 0 ? `+${m.delta}` : m.delta}
                          </span>
                        </div>
                        <p className="text-dark-500 mt-0.5">{m.base} → {m.compare}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {revisionDiff.diff.settings_changes.length > 0 && (
                  <div>
                    <p className="text-xs uppercase tracking-wide text-dark-400 mb-2">Settings Changes</p>
                    <div className="space-y-1 text-xs">
                      {revisionDiff.diff.settings_changes.map((c) => (
                        <div key={c.field} className="rounded-lg border border-dark-700 bg-dark-800/40 px-3 py-2 text-dark-300">
                          <span className="text-dark-100">{c.label}</span>: {c.base} → {c.compare}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="text-xs uppercase tracking-wide text-dark-400 mb-2">Voice Plan Changes</p>
                  <div className="text-xs text-dark-300 space-y-1">
                    <p>Assignments: {revisionDiff.diff.voice_plan.base_count} → {revisionDiff.diff.voice_plan.compare_count}</p>
                    {revisionDiff.diff.voice_plan.added_characters.length > 0 && (
                      <p>Added characters: {revisionDiff.diff.voice_plan.added_characters.join(', ')}</p>
                    )}
                    {revisionDiff.diff.voice_plan.removed_characters.length > 0 && (
                      <p>Removed characters: {revisionDiff.diff.voice_plan.removed_characters.join(', ')}</p>
                    )}
                    {revisionDiff.diff.voice_plan.changed_voices.length > 0 && (
                      <div className="space-y-1">
                        <p>Changed voices:</p>
                        {revisionDiff.diff.voice_plan.changed_voices.map((c) => (
                          <p key={c.character} className="text-dark-400">
                            {c.character}: {c.base_voice_id} → {c.compare_voice_id}
                          </p>
                        ))}
                      </div>
                    )}
                    {revisionDiff.diff.voice_plan.added_characters.length === 0 &&
                      revisionDiff.diff.voice_plan.removed_characters.length === 0 &&
                      revisionDiff.diff.voice_plan.changed_voices.length === 0 && (
                        <p className="text-dark-500">No voice-plan changes.</p>
                      )}
                  </div>
                </div>

                <div>
                  <p className="text-xs uppercase tracking-wide text-dark-400 mb-2">Cue Count Delta</p>
                  {Object.keys(revisionDiff.diff.cue_counts.delta).length > 0 ? (
                    <div className="flex flex-wrap gap-2 text-xs">
                      {Object.entries(revisionDiff.diff.cue_counts.delta).map(([k, delta]) => (
                        <span
                          key={k}
                          className={`px-2 py-1 rounded border ${
                            delta > 0
                              ? 'border-green-500/30 bg-green-500/10 text-green-300'
                              : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                          }`}
                        >
                          {k}: {delta > 0 ? `+${delta}` : delta}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-dark-500">No cue-count changes.</p>
                  )}
                </div>

                {!revisionDiff.diff.has_changes && (
                  <div className="text-xs rounded-lg border border-dark-700 bg-dark-800/40 px-3 py-2 text-dark-400">
                    No detected differences for the selected comparison pair.
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

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
