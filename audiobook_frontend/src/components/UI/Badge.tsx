import React from 'react';
import { clsx } from 'clsx';

const EMOTION_STYLES: Record<string, string> = {
  neutral:    'bg-dark-700 text-dark-300',
  happy:      'bg-yellow-500/15 text-yellow-300 border border-yellow-500/20',
  sad:        'bg-blue-500/15 text-blue-300 border border-blue-500/20',
  suspense:   'bg-red-500/15 text-red-300 border border-red-500/20',
  dramatic:   'bg-orange-500/15 text-orange-300 border border-orange-500/20',
  romantic:   'bg-pink-500/15 text-pink-300 border border-pink-500/20',
  action:     'bg-red-600/15 text-red-300 border border-red-600/20',
  mysterious: 'bg-purple-500/15 text-purple-300 border border-purple-500/20',
  peaceful:   'bg-green-500/15 text-green-300 border border-green-500/20',
};

const STATUS_STYLES: Record<string, string> = {
  pending:      'bg-dark-700 text-dark-300',
  extracting:   'bg-blue-500/15 text-blue-300 border border-blue-500/20',
  analyzing:    'bg-yellow-500/15 text-yellow-300 border border-yellow-500/20',
  synthesizing: 'bg-brand-500/15 text-brand-300 border border-brand-500/20',
  mixing:       'bg-purple-500/15 text-purple-300 border border-purple-500/20',
  completed:    'bg-green-500/15 text-green-300 border border-green-500/20',
  failed:       'bg-red-500/15 text-red-300 border border-red-500/20',
};

interface BadgeProps {
  type?: 'emotion' | 'status' | 'custom';
  value: string;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({ type = 'custom', value, className }) => {
  let style = 'bg-dark-700 text-dark-300';
  if (type === 'emotion') style = EMOTION_STYLES[value] ?? style;
  if (type === 'status')  style = STATUS_STYLES[value]  ?? style;

  return (
    <span className={clsx(
      'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize',
      style, className
    )}>
      {value}
    </span>
  );
};
