import React, { useState, useRef, useEffect } from 'react';
import { Play, Pause, Volume2, VolumeX } from 'lucide-react';

interface AudioPlayerProps {
  src: string;
  compact?: boolean;
}

export const AudioPlayer: React.FC<AudioPlayerProps> = ({ src, compact = false }) => {
  const audioRef                = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying]   = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted]       = useState(false);

  useEffect(() => { setPlaying(false); setProgress(0); }, [src]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (playing) { a.pause(); setPlaying(false); }
    else { a.play(); setPlaying(true); }
  };

  const fmt = (s: number) => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;

  return (
    <div className={`flex items-center gap-3 bg-dark-900/60 rounded-xl border border-dark-700 ${compact ? 'px-3 py-2' : 'px-4 py-3'}`}>
      <audio
        ref={audioRef}
        src={src}
        onTimeUpdate={() => {
          const a = audioRef.current;
          if (a) setProgress(a.currentTime / (a.duration || 1));
        }}
        onLoadedMetadata={() => { if (audioRef.current) setDuration(audioRef.current.duration); }}
        onEnded={() => setPlaying(false)}
        muted={muted}
      />
      <button onClick={toggle}
        className="w-8 h-8 rounded-full bg-brand-600 hover:bg-brand-500 flex items-center justify-center transition-colors flex-shrink-0">
        {playing ? <Pause size={14} className="text-white" /> : <Play size={14} className="text-white ml-0.5" />}
      </button>
      {!compact && (
        <>
          <div className="flex-1 h-1.5 bg-dark-700 rounded-full cursor-pointer"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const ratio = (e.clientX - rect.left) / rect.width;
              const a = audioRef.current;
              if (a) { a.currentTime = ratio * a.duration; }
            }}>
            <div className="h-full bg-gradient-brand rounded-full transition-all" style={{ width: `${progress * 100}%` }} />
          </div>
          <span className="text-xs text-dark-400 font-mono">
            {fmt(progress * duration)} / {fmt(duration)}
          </span>
        </>
      )}
      <button onClick={() => setMuted(!muted)} className="text-dark-400 hover:text-white transition-colors">
        {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
      </button>
    </div>
  );
};
