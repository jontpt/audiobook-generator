import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Mail, Lock, Headphones, Eye, EyeOff, ArrowRight } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { authApi } from '../api/auth';
import { Button } from '../components/UI/Button';
import { Input } from '../components/UI/Input';
import toast from 'react-hot-toast';

export const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading]   = useState(false);
  const [errors, setErrors]     = useState<Record<string, string>>({});
  const { login } = useAuth();
  const navigate  = useNavigate();

  const validate = () => {
    const e: Record<string, string> = {};
    if (!username.trim()) e.username = 'Username or email is required';
    if (!password)        e.password = 'Password is required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setLoading(true);
    try {
      const tokens = await authApi.login({ username, password });
      await login(tokens.access_token);
      toast.success('Welcome back!');
      navigate('/dashboard');
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? 'Invalid credentials. Please try again.';
      toast.error(msg);
      setErrors({ password: msg });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-dark-950 flex items-center justify-center p-4">
      {/* Background gradient */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-brand-600/20 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-accent-teal/10 rounded-full blur-3xl" />
      </div>

      <motion.div
        className="relative w-full max-w-md"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-brand shadow-glow-brand mb-4">
            <Headphones size={28} className="text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white">AudioBook AI</h1>
          <p className="text-dark-400 mt-1">Sign in to your studio</p>
        </div>

        {/* Card */}
        <div className="bg-dark-900/80 backdrop-blur border border-dark-800 rounded-2xl p-8 shadow-card">
          <form onSubmit={handleSubmit} className="space-y-5">
            <Input
              label="Username or Email"
              type="text"
              placeholder="your@email.com"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              error={errors.username}
              icon={<Mail size={16} />}
              autoComplete="username"
            />
            <Input
              label="Password"
              type={showPass ? 'text' : 'password'}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={errors.password}
              icon={<Lock size={16} />}
              iconRight={
                <button type="button" onClick={() => setShowPass(!showPass)} className="hover:text-white transition-colors">
                  {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              }
              autoComplete="current-password"
            />
            <Button type="submit" variant="primary" size="lg" loading={loading}
              className="w-full" iconRight={<ArrowRight size={16} />}>
              Sign in
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-dark-400 text-sm">
              Don't have an account?{' '}
              <Link to="/register" className="text-brand-400 hover:text-brand-300 font-medium transition-colors">
                Create one free
              </Link>
            </p>
          </div>
        </div>

        {/* Demo hint */}
        <p className="text-center text-xs text-dark-500 mt-4">
          Demo: <span className="font-mono text-dark-400">demo / demo1234</span>
        </p>
      </motion.div>
    </div>
  );
};
