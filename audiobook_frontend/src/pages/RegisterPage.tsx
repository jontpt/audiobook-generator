import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Mail, Lock, User, Headphones, Eye, EyeOff, ArrowRight, CheckCircle } from 'lucide-react';
import { authApi } from '../api/auth';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import toast from 'react-hot-toast';

const PERKS = [
  'Multi-voice narration with AI characters',
  'Automatic dialogue & emotion detection',
  'ElevenLabs TTS integration',
  'Export to MP3 or M4B with chapter markers',
];

export const RegisterPage: React.FC = () => {
  const [form, setForm]       = useState({ username: '', email: '', password: '', confirm: '' });
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading]   = useState(false);
  const [errors, setErrors]     = useState<Record<string, string>>({});
  const navigate = useNavigate();

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.username.trim())    e.username = 'Username is required';
    if (form.username.length < 3) e.username = 'At least 3 characters';
    if (!form.email.includes('@')) e.email   = 'Valid email required';
    if (form.password.length < 8)  e.password = 'At least 8 characters';
    if (form.password !== form.confirm) e.confirm = 'Passwords do not match';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setLoading(true);
    try {
      await authApi.register({ username: form.username, email: form.email, password: form.password });
      toast.success('Account created! Please sign in.');
      navigate('/login');
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? 'Registration failed.';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-dark-950 flex">
      {/* Left panel — perks */}
      <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-dark-900 to-dark-800 flex-col justify-center px-16 border-r border-dark-800">
        <div className="flex items-center gap-3 mb-10">
          <div className="w-10 h-10 rounded-xl bg-gradient-brand flex items-center justify-center shadow-glow-sm">
            <Headphones size={20} className="text-white" />
          </div>
          <span className="text-xl font-bold text-white">AudioBook AI</span>
        </div>
        <h2 className="text-4xl font-bold text-white leading-tight mb-4">
          Transform any book into a full-cast audiobook
        </h2>
        <p className="text-dark-300 mb-10 leading-relaxed">
          AI-powered narration with distinct voices per character, emotion-aware
          synthesis, and professional audio mixing — all automated.
        </p>
        <div className="space-y-4">
          {PERKS.map((perk, i) => (
            <motion.div key={i}
              className="flex items-center gap-3"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 + 0.3 }}
            >
              <div className="w-6 h-6 rounded-full bg-green-500/20 border border-green-500/30 flex items-center justify-center flex-shrink-0">
                <CheckCircle size={14} className="text-green-400" />
              </div>
              <span className="text-dark-200 text-sm">{perk}</span>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-8 relative">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-40 -right-40 w-96 h-96 bg-brand-600/15 rounded-full blur-3xl" />
        </div>
        <motion.div className="relative w-full max-w-md"
          initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}>
          <div className="mb-8">
            <h2 className="text-2xl font-bold text-white">Create your account</h2>
            <p className="text-dark-400 mt-1">Free to start — no credit card required</p>
          </div>

          <div className="bg-dark-900/80 backdrop-blur border border-dark-800 rounded-2xl p-8 shadow-card">
            <form onSubmit={handleSubmit} className="space-y-4">
              <Input label="Username" placeholder="johndoe"
                value={form.username} onChange={set('username')} error={errors.username}
                icon={<User size={16} />} autoComplete="username" />
              <Input label="Email address" type="email" placeholder="you@example.com"
                value={form.email} onChange={set('email')} error={errors.email}
                icon={<Mail size={16} />} autoComplete="email" />
              <Input label="Password" type={showPass ? 'text' : 'password'}
                placeholder="Min. 8 characters"
                value={form.password} onChange={set('password')} error={errors.password}
                icon={<Lock size={16} />}
                iconRight={
                  <button type="button" onClick={() => setShowPass(!showPass)} className="hover:text-white transition-colors">
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                } />
              <Input label="Confirm password" type={showPass ? 'text' : 'password'}
                placeholder="Repeat password"
                value={form.confirm} onChange={set('confirm')} error={errors.confirm}
                icon={<Lock size={16} />} />
              <Button type="submit" variant="primary" size="lg" loading={loading}
                className="w-full mt-2" iconRight={<ArrowRight size={16} />}>
                Create Account
              </Button>
            </form>
            <p className="text-center text-dark-400 text-sm mt-5">
              Already have an account?{' '}
              <Link to="/login" className="text-brand-400 hover:text-brand-300 font-medium transition-colors">
                Sign in
              </Link>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
};
