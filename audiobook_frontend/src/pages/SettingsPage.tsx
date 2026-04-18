import React, { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Key, Plus, Trash2, CheckCircle2, XCircle, Eye, EyeOff, 
  User, Lock, Shield, Zap, RefreshCw, Upload, FolderOpen, Music2, Waves, Clapperboard,
} from 'lucide-react';
import { settingsApi } from '../api/settings';
import { authApi } from '../api/auth';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import { Modal } from '../components/UI/Modal';
import type { ApiKey } from '../types';
import toast from 'react-hot-toast';

const SERVICE_META: Record<string, { name: string; icon: string; color: string; hint: string }> = {
  elevenlabs: { name: 'ElevenLabs', icon: '🎙️', color: 'text-brand-400',    hint: 'sk-...' },
  mubert:     { name: 'Mubert',     icon: '🎵', color: 'text-accent-teal',  hint: 'Your Mubert API token' },
  jamendo:    { name: 'Jamendo',    icon: '🎼', color: 'text-accent-blue',  hint: 'Your Jamendo client_id' },
  soundraw:   { name: 'Soundraw',   icon: '🎶', color: 'text-accent-amber', hint: 'Your Soundraw API key' },
};

export const SettingsPage: React.FC = () => {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const sfxFileInputRef = useRef<HTMLInputElement | null>(null);

  // ── API Keys state ──────────────────────────────────────────────────────
  const [addKeyModal, setAddKeyModal] = useState(false);
  const [newKey, setNewKey]           = useState({ service: 'elevenlabs', label: '', key: '' });
  const [showKey, setShowKey]         = useState(false);
  const [sfxZipFile, setSfxZipFile]   = useState<File | null>(null);

  // ── Password change state ────────────────────────────────────────────────
  const [pwdForm, setPwdForm]     = useState({ current: '', next: '', confirm: '' });
  const [showPwds, setShowPwds]   = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);

  const { data: apiKeys = [], isLoading: keysLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: settingsApi.getApiKeys,
  });

  const { data: sfxInventory, isLoading: sfxLoading } = useQuery({
    queryKey: ['sfx-library'],
    queryFn: settingsApi.getSfxLibraryInventory,
  });

  const addKeyMutation = useMutation({
    mutationFn: () => settingsApi.addApiKey(newKey.service, newKey.label, newKey.key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      setAddKeyModal(false);
      setNewKey({ service: 'elevenlabs', label: '', key: '' });
      setShowKey(false);
      toast.success('API key saved successfully');
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail ?? 'Failed to save key'),
  });

  const deleteKeyMutation = useMutation({
    mutationFn: settingsApi.deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      toast.success('API key removed');
    },
  });

  const validateMutation = useMutation({
    mutationFn: settingsApi.validateApiKey,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      toast.success(data.valid ? 'Key is valid ✓' : 'Key is invalid ✗');
    },
  });

  const uploadSfxMutation = useMutation({
    mutationFn: () => {
      if (!sfxZipFile) {
        throw new Error('Choose a ZIP file first');
      }
      return settingsApi.uploadSfxLibrary(sfxZipFile);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sfx-library'] });
      setSfxZipFile(null);
      if (sfxFileInputRef.current) sfxFileInputRef.current.value = '';
      const report = data.import_report;
      toast.success(`Imported ${report.imported_count} audio asset(s)`);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? err?.message ?? 'Failed to upload SFX library');
    },
  });

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pwdForm.next !== pwdForm.confirm) { toast.error('Passwords do not match'); return; }
    if (pwdForm.next.length < 8)          { toast.error('Password must be 8+ chars'); return; }
    setPwdLoading(true);
    try {
      await authApi.changePassword(pwdForm.current, pwdForm.next);
      toast.success('Password updated!');
      setPwdForm({ current: '', next: '', confirm: '' });
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Failed to change password');
    } finally {
      setPwdLoading(false);
    }
  };

  // Reset modal state cleanly when opening
  const openAddKeyModal = () => {
    setNewKey({ service: 'elevenlabs', label: '', key: '' });
    setShowKey(false);
    setAddKeyModal(true);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-dark-400 mt-1">Manage your account and API integrations</p>
      </div>

      {/* ── Profile ──────────────────────────────────────────────────────── */}
      <section className="bg-dark-800/60 border border-dark-700 rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-5">
          <User size={18} className="text-brand-400" /> Profile
        </h2>
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-full bg-gradient-brand flex items-center justify-center text-white text-xl font-bold">
            {user?.username?.[0]?.toUpperCase()}
          </div>
          <div>
            <p className="font-semibold text-white">{user?.username}</p>
            <p className="text-sm text-dark-400">{user?.email}</p>
            <p className="text-xs text-dark-500 mt-0.5">
              Member since {user?.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
            </p>
          </div>
        </div>
      </section>

      {/* ── API Keys ──────────────────────────────────────────────────────── */}
      <section className="bg-dark-800/60 border border-dark-700 rounded-2xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Key size={18} className="text-brand-400" /> API Keys
          </h2>
          <Button variant="outline" size="sm" icon={<Plus size={14} />} onClick={openAddKeyModal}>
            Add Key
          </Button>
        </div>

        {/* Service status cards */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          {Object.entries(SERVICE_META).map(([svc, meta]) => {
            const existing = apiKeys.find(k => k.service === svc);
            return (
              <div key={svc} className={`rounded-xl border p-3 text-center transition-all
                ${existing ? 'border-green-500/30 bg-green-500/5' : 'border-dark-700 bg-dark-900/40'}`}>
                <span className="text-2xl">{meta.icon}</span>
                <p className={`text-sm font-medium mt-1 ${meta.color}`}>{meta.name}</p>
                <p className="text-xs mt-1">
                  {existing
                    ? <span className="text-green-400 flex items-center justify-center gap-1"><CheckCircle2 size={10} /> Connected</span>
                    : <span className="text-dark-500">Not configured</span>}
                </p>
              </div>
            );
          })}
        </div>

        {/* Key list */}
        {keysLoading ? (
          <div className="space-y-2">
            {[1, 2].map(i => <div key={i} className="h-14 bg-dark-700 rounded-xl animate-pulse" />)}
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="text-center py-8 text-dark-500">
            <Key size={28} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">No API keys configured yet.</p>
            <p className="text-xs mt-1">Add your ElevenLabs key to enable real TTS.</p>
          </div>
        ) : (
          <div className="space-y-3">
            <AnimatePresence>
              {apiKeys.map(key => {
                const meta = SERVICE_META[key.service];
                return (
                  <motion.div key={key.id}
                    className="flex items-center gap-3 bg-dark-900/50 border border-dark-700 rounded-xl px-4 py-3"
                    initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }}>
                    <span className="text-lg">{meta?.icon ?? '🔑'}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white">{key.label || meta?.name}</span>
                        {key.is_valid === true  && <CheckCircle2 size={13} className="text-green-400" />}
                        {key.is_valid === false && <XCircle      size={13} className="text-red-400" />}
                      </div>
                      <p className="text-xs text-dark-400 font-mono">{key.key_preview}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="ghost" size="sm" icon={<RefreshCw size={12} />}
                        onClick={() => validateMutation.mutate(key.id)}
                        loading={validateMutation.isPending}
                        className="text-xs">
                        Test
                      </Button>
                      <Button variant="danger" size="sm" icon={<Trash2 size={12} />}
                        onClick={() => { if (confirm('Remove this key?')) deleteKeyMutation.mutate(key.id); }}>
                        Remove
                      </Button>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}
      </section>

      {/* ── Radio-play SFX Library ────────────────────────────────────────── */}
      <section className="bg-dark-800/60 border border-dark-700 rounded-2xl p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <FolderOpen size={18} className="text-brand-400" /> Radio-play SFX Library
            </h2>
            <p className="text-sm text-dark-400 mt-1">
              Upload a ZIP pack with ambience/foley/music clips for deterministic cue playback.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            icon={<RefreshCw size={14} />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ['sfx-library'] })}
            loading={sfxLoading}
          >
            Refresh
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded-xl border border-dark-700 bg-dark-900/40 p-3">
            <p className="text-xs uppercase tracking-wide text-dark-400">Ambience</p>
            <p className="mt-1 text-xl font-semibold text-white flex items-center gap-2">
              <Waves size={16} className="text-accent-blue" />
              {sfxInventory?.categories?.ambience?.count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-dark-700 bg-dark-900/40 p-3">
            <p className="text-xs uppercase tracking-wide text-dark-400">Foley</p>
            <p className="mt-1 text-xl font-semibold text-white flex items-center gap-2">
              <Clapperboard size={16} className="text-accent-amber" />
              {sfxInventory?.categories?.foley?.count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-dark-700 bg-dark-900/40 p-3">
            <p className="text-xs uppercase tracking-wide text-dark-400">Music</p>
            <p className="mt-1 text-xl font-semibold text-white flex items-center gap-2">
              <Music2 size={16} className="text-accent-teal" />
              {sfxInventory?.categories?.music?.count ?? 0}
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-dark-700 bg-dark-900/40 p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={sfxFileInputRef}
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => setSfxZipFile(e.target.files?.[0] ?? null)}
              className="block w-full max-w-md text-sm text-dark-300 file:mr-4 file:rounded-lg file:border-0 file:bg-dark-700 file:px-3 file:py-2 file:text-dark-100 hover:file:bg-dark-600"
            />
            <Button
              variant="primary"
              size="sm"
              icon={<Upload size={14} />}
              disabled={!sfxZipFile}
              loading={uploadSfxMutation.isPending}
              onClick={() => uploadSfxMutation.mutate()}
            >
              Import ZIP
            </Button>
          </div>
          <p className="text-xs text-dark-500">
            Expected structure supports folders like <span className="font-mono">ambience/</span>, <span className="font-mono">foley/</span>, <span className="font-mono">music/</span>.
            Supported audio: wav, mp3, ogg, flac, m4a.
          </p>
          {uploadSfxMutation.data && (
            <div className="text-xs rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-green-300 space-y-1">
              <p>Imported: {uploadSfxMutation.data.import_report.imported_count}</p>
              <p>
                Skipped (non-audio / too-large / invalid):{' '}
                {uploadSfxMutation.data.import_report.skipped_non_audio} /{' '}
                {uploadSfxMutation.data.import_report.skipped_too_large} /{' '}
                {uploadSfxMutation.data.import_report.skipped_bad_entries}
              </p>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          {(['ambience', 'foley', 'music'] as const).map((category) => {
            const files = sfxInventory?.categories?.[category]?.files ?? [];
            return (
              <div key={category} className="rounded-xl border border-dark-700 bg-dark-900/30 p-3">
                <p className="text-dark-300 capitalize font-medium mb-2">{category} sample files</p>
                {files.length === 0 ? (
                  <p className="text-dark-500">No files yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {files.map((f) => (
                      <li key={f} className="text-dark-400 truncate">{f}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Security ──────────────────────────────────────────────────────── */}
      <section className="bg-dark-800/60 border border-dark-700 rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-5">
          <Shield size={18} className="text-brand-400" /> Security
        </h2>
        <form onSubmit={handlePasswordChange} className="space-y-4 max-w-sm">
          <Input label="Current password" type={showPwds ? 'text' : 'password'}
            value={pwdForm.current}
            onChange={e => setPwdForm(f => ({ ...f, current: e.target.value }))}
            autoComplete="current-password"
            icon={<Lock size={14} />} />
          <Input label="New password" type={showPwds ? 'text' : 'password'}
            value={pwdForm.next}
            onChange={e => setPwdForm(f => ({ ...f, next: e.target.value }))}
            autoComplete="new-password"
            hint="Minimum 8 characters"
            icon={<Lock size={14} />} />
          <Input label="Confirm new password" type={showPwds ? 'text' : 'password'}
            value={pwdForm.confirm}
            onChange={e => setPwdForm(f => ({ ...f, confirm: e.target.value }))}
            autoComplete="new-password"
            icon={<Lock size={14} />} />
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" size="sm" loading={pwdLoading}>
              Update Password
            </Button>
            <button type="button"
              className="text-xs text-dark-400 hover:text-white flex items-center gap-1"
              onClick={() => setShowPwds(!showPwds)}>
              {showPwds ? <EyeOff size={12} /> : <Eye size={12} />}
              {showPwds ? 'Hide' : 'Show'}
            </button>
          </div>
        </form>
      </section>

      {/* ── Add Key Modal ─────────────────────────────────────────────────── */}
      <Modal open={addKeyModal} onClose={() => setAddKeyModal(false)} title="Add API Key">
        {/*
          autoComplete on each input:
          - Label      → "off"           stops browser treating it as "username"
          - API Key    → "new-password"  the only value Chrome/Firefox honour for
                                         password-type inputs; "off" is ignored
        */}
        <div className="space-y-4">

          {/* Service selector */}
          <div>
            <label className="text-sm font-medium text-dark-200 mb-1.5 block">Service</label>
            <select
              value={newKey.service}
              onChange={e => setNewKey(k => ({ ...k, service: e.target.value }))}
              className="w-full bg-dark-800 border border-dark-700 text-white rounded-xl px-3 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500/50">
              {Object.entries(SERVICE_META).map(([svc, meta]) => (
                <option key={svc} value={svc}>{meta.icon} {meta.name}</option>
              ))}
            </select>
          </div>

          {/* Label — autoComplete="off" prevents browser injecting the saved username */}
          <Input
            label="Label (optional)"
            placeholder={`My ${SERVICE_META[newKey.service]?.name} key`}
            value={newKey.label}
            onChange={e => setNewKey(k => ({ ...k, label: e.target.value }))}
            autoComplete="off"
          />

          {/* API Key — autoComplete="new-password" prevents browser injecting the saved password */}
          <div>
            <Input
              label="API Key"
              type={showKey ? 'text' : 'password'}
              placeholder={SERVICE_META[newKey.service]?.hint}
              value={newKey.key}
              onChange={e => setNewKey(k => ({ ...k, key: e.target.value }))}
              icon={<Key size={14} />}
              autoComplete="new-password"
              iconRight={
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="hover:text-white transition-colors">
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              }
            />
            <p className="text-xs text-dark-500 mt-1.5">🔒 Keys are encrypted and stored securely</p>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <Button variant="secondary" className="flex-1" onClick={() => setAddKeyModal(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              className="flex-1"
              disabled={!newKey.key.trim()}
              loading={addKeyMutation.isPending}
              onClick={() => addKeyMutation.mutate()}
              icon={<Zap size={14} />}>
              Save Key
            </Button>
          </div>

        </div>
      </Modal>
    </div>
  );
};
