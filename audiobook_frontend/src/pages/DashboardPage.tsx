import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, BookOpen, Headphones, Mic2, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { booksApi } from '../api/books';
import { BookCard } from '../components/Books/BookCard';
import { Button } from '../components/UI/Button';
import { useAuth } from '../contexts/AuthContext';
import toast from 'react-hot-toast';
import packageJson from '../../package.json';

const UI_VERSION = String(packageJson.version || 'unknown');
const UI_REVISION = String(import.meta.env.VITE_APP_REVISION || 'local');

const StatCard: React.FC<{ icon: React.ReactNode; label: string; value: string | number; color: string }> =
  ({ icon, label, value, color }) => (
    <div className="bg-dark-800/60 border border-dark-700 rounded-2xl p-5">
      <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center mb-3`}>{icon}</div>
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-sm text-dark-400 mt-0.5">{label}</p>
    </div>
  );

export const DashboardPage: React.FC = () => {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const { data: books = [], isLoading } = useQuery({
    queryKey: ['books'],
    queryFn: booksApi.list,
    refetchInterval: (data) => {
      const hasProcessing = (Array.isArray(data) ? data : []).some(
        (b: any) => !['completed', 'failed', 'pending'].includes(b.status)
      );
      return hasProcessing ? 3000 : false;
    },
  });

  const { data: health } = useQuery({
    queryKey: ['health-version'],
    queryFn: async () => {
      const res = await fetch('/health');
      if (!res.ok) throw new Error('Health check failed');
      return res.json() as Promise<{ version?: string }>;
    },
    staleTime: 60_000,
    retry: 0,
  });

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this audiobook and all its audio files?')) return;
    try {
      await booksApi.delete(id);
      queryClient.invalidateQueries({ queryKey: ['books'] });
      toast.success('Book deleted');
    } catch {
      toast.error('Failed to delete book');
    }
  };

  const completed   = books.filter(b => b.status === 'completed').length;
  const processing  = books.filter(b => !['completed','failed','pending'].includes(b.status)).length;
  const totalWords  = books.reduce((s, b) => s + (b.total_words || 0), 0);
  const totalChars  = books.reduce((s, b) => s + (b.character_count || 0), 0);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Welcome back, <span className="text-brand-400">{user?.username}</span> 👋
          </h1>
          <p className="text-dark-400 mt-1">Your audiobook studio</p>
          <p className="text-xs text-dark-500 mt-1 font-mono">
            API v{health?.version ?? '—'} · UI v{UI_VERSION} · rev {UI_REVISION}
          </p>
        </div>
        <Link to="/upload">
          <Button variant="primary" icon={<Plus size={16} />}>New Audiobook</Button>
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<BookOpen size={18} className="text-brand-400" />} label="Total Books"
          value={books.length} color="bg-brand-500/15 border border-brand-500/20" />
        <StatCard icon={<Headphones size={18} className="text-green-400" />} label="Completed"
          value={completed} color="bg-green-500/15 border border-green-500/20" />
        <StatCard icon={<Mic2 size={18} className="text-accent-teal" />} label="Characters"
          value={totalChars} color="bg-teal-500/15 border border-teal-500/20" />
        <StatCard icon={<TrendingUp size={18} className="text-accent-amber" />} label="Words Processed"
          value={totalWords > 1000 ? `${(totalWords/1000).toFixed(1)}k` : totalWords}
          color="bg-amber-500/15 border border-amber-500/20" />
      </div>

      {/* Books grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1,2,3].map(i => (
            <div key={i} className="bg-dark-800/40 border border-dark-700 rounded-2xl p-5 animate-pulse h-40" />
          ))}
        </div>
      ) : books.length === 0 ? (
        <motion.div
          className="flex flex-col items-center justify-center py-20 text-center"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
        >
          <div className="w-20 h-20 rounded-2xl bg-dark-800 border border-dark-700 flex items-center justify-center mb-4">
            <BookOpen size={32} className="text-dark-500" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No audiobooks yet</h3>
          <p className="text-dark-400 mb-6 max-w-sm">
            Upload a PDF, DOCX, ePub, or TXT file and let AI transform it into a full-cast audiobook.
          </p>
          <Link to="/upload">
            <Button variant="primary" icon={<Plus size={16} />}>Create your first audiobook</Button>
          </Link>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <AnimatePresence>
            {books.map(book => (
              <div key={book.id} className="relative">
                <BookCard book={book} onDelete={handleDelete} />
              </div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
};
