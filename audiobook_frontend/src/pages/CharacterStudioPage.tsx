import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Mic2, Play, Check, Search } from 'lucide-react';
import { charactersApi, voicesApi } from '../api/characters';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import { Modal } from '../components/UI/Modal';
import { Badge } from '../components/UI/Badge';
import type { Character, VoiceInfo } from '../types';
import toast from 'react-hot-toast';

const GenderDot: Record<string, string> = {
  male:    'bg-blue-400',
  female:  'bg-pink-400',
  neutral: 'bg-dark-400',
};

export const CharacterStudioPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [selected, setSelected]     = useState<Character | null>(null);
  const [voiceSearch, setVoiceSearch] = useState('');
  const [genderFilter, setGenderFilter] = useState<string>('');

  const { data: characters = [], isLoading } = useQuery({
    queryKey: ['characters', id],
    queryFn: () => charactersApi.list(id!),
    enabled: !!id,
  });

  const { data: voices = [] } = useQuery({
    queryKey: ['voices', genderFilter],
    queryFn: () => voicesApi.list(genderFilter || undefined),
  });

  const updateMutation = useMutation({
    mutationFn: ({ charId, voiceId }: { charId: string; voiceId: string }) =>
      charactersApi.update(id!, charId, { voice_id: voiceId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['characters', id] });
      toast.success('Voice updated!');
    },
    onError: () => toast.error('Failed to update voice'),
  });

  const filteredVoices = voices.filter(v =>
    v.name.toLowerCase().includes(voiceSearch.toLowerCase()) ||
    v.description.toLowerCase().includes(voiceSearch.toLowerCase())
  );

  return (
    <div>
      <Link to={`/books/${id}`} className="inline-flex items-center gap-2 text-dark-400 hover:text-white transition-colors mb-6 text-sm">
        <ArrowLeft size={16} /> Back to Book
      </Link>

      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-brand-500/15 border border-brand-500/20 flex items-center justify-center">
          <Mic2 size={18} className="text-brand-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Character Studio</h1>
          <p className="text-dark-400">Assign and preview voices for each character</p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1,2,3,4].map(i => <div key={i} className="h-24 bg-dark-800/40 rounded-2xl animate-pulse border border-dark-700" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {characters.map(char => (
            <motion.div key={char.id}
              className="bg-dark-800/60 border border-dark-700 rounded-2xl p-4 hover:border-dark-600 transition-all"
              whileHover={{ y: -2 }}>
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="w-12 h-12 rounded-full bg-gradient-brand/20 border border-brand-500/20 flex items-center justify-center text-lg font-bold text-brand-300">
                    {char.name[0]?.toUpperCase()}
                  </div>
                  <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-dark-800 ${GenderDot[char.gender]}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-white">{char.name}</h3>
                    <span className="text-xs text-dark-500">{char.appearance_count}x</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-dark-400 capitalize">{char.gender} · {char.age_group}</span>
                    {char.voice_name && (
                      <span className="text-xs text-brand-400">→ {char.voice_name}</span>
                    )}
                  </div>
                </div>
                <Button variant="outline" size="sm" icon={<Mic2 size={13} />}
                  onClick={() => setSelected(char)}>
                  Voice
                </Button>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* Voice selector modal */}
      <Modal open={!!selected} onClose={() => setSelected(null)}
        title={`Assign Voice — ${selected?.name}`} maxWidth="max-w-2xl">
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex gap-3">
            <Input placeholder="Search voices…" value={voiceSearch}
              onChange={e => setVoiceSearch(e.target.value)}
              icon={<Search size={14} />} className="flex-1" />
            <select value={genderFilter} onChange={e => setGenderFilter(e.target.value)}
              className="bg-dark-800 border border-dark-700 text-white rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/50">
              <option value="">All genders</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="neutral">Neutral</option>
            </select>
          </div>

          {/* Voice list */}
          <div className="grid grid-cols-1 gap-2 max-h-80 overflow-y-auto pr-1 custom-scroll">
            {filteredVoices.map(voice => {
              const isActive = selected?.voice_id === voice.voice_id;
              return (
                <div key={voice.voice_id}
                  className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all
                    ${isActive ? 'border-brand-500/50 bg-brand-500/10' : 'border-dark-700 bg-dark-800/40 hover:border-dark-600 hover:bg-dark-800/80'}`}
                  onClick={() => {
                    if (!selected) return;
                    updateMutation.mutate({ charId: selected.id, voiceId: voice.voice_id });
                    setSelected(prev => prev ? { ...prev, voice_id: voice.voice_id, voice_name: voice.name } : null);
                  }}>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold
                    ${voice.gender === 'male' ? 'bg-blue-500/20 text-blue-300' : voice.gender === 'female' ? 'bg-pink-500/20 text-pink-300' : 'bg-dark-700 text-dark-300'}`}>
                    {voice.name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">{voice.name}</span>
                      <span className="text-xs text-dark-500 capitalize">{voice.accent}</span>
                    </div>
                    <p className="text-xs text-dark-400 truncate">{voice.description}</p>
                  </div>
                  {isActive && <Check size={16} className="text-brand-400 flex-shrink-0" />}
                </div>
              );
            })}
          </div>

          <Button variant="primary" className="w-full" onClick={() => setSelected(null)}>
            Done
          </Button>
        </div>
      </Modal>
    </div>
  );
};
