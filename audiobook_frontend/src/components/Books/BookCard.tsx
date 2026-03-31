import React from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { BookOpen, Mic2, Trash2, Clock, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import type { Book } from '../../types';
import { Badge } from '../UI/Badge';
import { Button } from '../UI/Button';

const STATUS_ICON: Record<string, React.ReactNode> = {
  completed:    <CheckCircle2 size={14} className="text-green-400" />,
  failed:       <AlertCircle size={14} className="text-red-400" />,
  pending:      <Clock size={14} className="text-dark-400" />,
  synthesizing: <Loader2 size={14} className="text-brand-400 animate-spin" />,
  mixing:       <Loader2 size={14} className="text-purple-400 animate-spin" />,
  analyzing:    <Loader2 size={14} className="text-yellow-400 animate-spin" />,
  extracting:   <Loader2 size={14} className="text-blue-400 animate-spin" />,
};

interface BookCardProps {
  book: Book;
  onDelete?: (id: string) => void;
}

export const BookCard: React.FC<BookCardProps> = ({ book, onDelete }) => {
  const navigate = useNavigate();
  const isProcessing = !['completed', 'failed', 'pending'].includes(book.status);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="bg-dark-800/60 border border-dark-700 rounded-2xl p-5 hover:border-dark-600 hover:shadow-card-hover transition-all duration-200 group cursor-pointer"
      onClick={() => navigate(`/books/${book.id}`)}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-gradient-brand/10 border border-brand-500/20 flex items-center justify-center flex-shrink-0">
            <BookOpen size={18} className="text-brand-400" />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-white truncate group-hover:text-brand-300 transition-colors">
              {book.title}
            </h3>
            <p className="text-xs text-dark-400 truncate">{book.author}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {STATUS_ICON[book.status]}
          <Badge type="status" value={book.status} />
        </div>
      </div>

      {/* Progress bar (if processing) */}
      {isProcessing && (
        <div className="mb-4">
          <div className="flex justify-between text-xs text-dark-400 mb-1">
            <span className="capitalize">{book.status}…</span>
            <span>{Math.round(book.progress * 100)}%</span>
          </div>
          <div className="h-1.5 bg-dark-700 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-brand rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${book.progress * 100}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs text-dark-400">
        {book.chapter_count > 0 && (
          <span className="flex items-center gap-1">
            <BookOpen size={11} />
            {book.chapter_count} chapters
          </span>
        )}
        {book.character_count > 0 && (
          <span className="flex items-center gap-1">
            <Mic2 size={11} />
            {book.character_count} voices
          </span>
        )}
        {book.total_words > 0 && (
          <span>{book.total_words.toLocaleString()} words</span>
        )}
        {book.file_type && (
          <span className="ml-auto font-mono uppercase text-dark-500">
            {book.file_type}
          </span>
        )}
      </div>

      {/* Delete */}
      {onDelete && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(book.id); }}
          className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-dark-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
        >
          <Trash2 size={14} />
        </button>
      )}
    </motion.div>
  );
};
