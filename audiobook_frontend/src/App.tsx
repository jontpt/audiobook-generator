import React from 'react';
import {
  BrowserRouter, Routes, Route, Navigate, Outlet,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Layout } from './components/Layout/Layout';

import { LoginPage }           from './pages/LoginPage';
import { RegisterPage }        from './pages/RegisterPage';
import { DashboardPage }       from './pages/DashboardPage';
import { UploadPage }          from './pages/UploadPage';
import { BookDetailPage }      from './pages/BookDetailPage';
import { CharacterStudioPage } from './pages/CharacterStudioPage';
import { SettingsPage }        from './pages/SettingsPage';
import { WorkflowHubPage }     from './pages/WorkflowHubPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

// ── Protected routes ──────────────────────────────────────────────────────────
const RequireAuth: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return (
    <div className="min-h-screen bg-dark-950 flex items-center justify-center">
      <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
  return isAuthenticated ? <Outlet /> : <Navigate to="/login" replace />;
};

const PublicOnly: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return null;
  return isAuthenticated ? <Navigate to="/dashboard" replace /> : <Outlet />;
};

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public */}
            <Route element={<PublicOnly />}>
              <Route path="/login"    element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
            </Route>

            {/* Protected */}
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route index                             element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard"                 element={<DashboardPage />} />
                <Route path="/upload"                    element={<UploadPage />} />
                <Route path="/workflow"                  element={<WorkflowHubPage />} />
                <Route path="/books/:id"                 element={<BookDetailPage />} />
                <Route path="/books/:id/characters"      element={<CharacterStudioPage />} />
                <Route path="/settings"                  element={<SettingsPage />} />
              </Route>
            </Route>

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>

        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: '#1a1a2e',
              color: '#fff',
              border: '1px solid #2a2a48',
              borderRadius: '12px',
              fontSize: '14px',
            },
            success: { iconTheme: { primary: '#7c2dfa', secondary: '#fff' } },
          }}
        />
      </AuthProvider>
    </QueryClientProvider>
  );
}
