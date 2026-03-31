import React from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useApp } from './context/AppContext';
import Sidebar from './components/layout/Sidebar';
import ChatPage from './pages/ChatPage';
import ProfilePage from './pages/ProfilePage';
import ProfileConflictsPage from './pages/ProfileConflictsPage';
import SettingsPage from './pages/SettingsPage';
import PlansPage from './pages/PlansPage';
import AnalyticsPage from './pages/AnalyticsPage';
import ErrorBoundary from './components/shared/ErrorBoundary';
import { Menu, MessageSquarePlus, Sparkles, ChevronRight } from 'lucide-react';

const PAGE_META = {
  '/chat': {
    title: 'Student Guidance',
    description: 'Personalized academic, career, and planning help.',
  },
  '/profile': {
    title: 'Student Memory',
    description: 'Review the profile, evidence, confidence, and learned context.',
  },
  '/profile/conflicts': {
    title: 'Resolve Conflicts',
    description: 'Review conflicting profile signals and choose the current one.',
  },
  '/plans': {
    title: 'Plans & Follow-ups',
    description: 'Track saved recommendations and revisit next actions.',
  },
  '/analytics': {
    title: 'Runtime Analytics',
    description: 'Inspect planner, retrieval, and system health signals.',
  },
  '/settings': {
    title: 'Settings',
    description: 'Tune guardrails, theme, and system preferences.',
  },
};

export default function App() {
  const { state, dispatch, createSession } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const meta = PAGE_META[location.pathname] || PAGE_META['/chat'];
  const activeProfile = state.profiles.find((profile) => profile.student_id === state.activeStudentId);
  const isChatRoute = location.pathname === '/chat';
  const profileInitial = (activeProfile?.name || 'Student').trim().charAt(0).toUpperCase() || 'S';

  return (
    <ErrorBoundary>
      <div className="flex h-screen bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.08),transparent_30%),linear-gradient(to_bottom,hsl(var(--background)),hsl(var(--background)))]">
        {/* Sidebar */}
        <Sidebar
          open={state.sidebarOpen}
          onToggle={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
        />

        {/* Main Content */}
        <main className="flex-1 flex min-w-0 flex-col overflow-hidden">
          <header className="border-b border-border/70 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/70">
            <div className="flex items-center justify-between gap-3 px-4 py-2.5 md:px-5">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  onClick={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border bg-card text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  title={state.sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                >
                  <Menu className="h-4 w-4" />
                </button>
                <div className="min-w-0 space-y-0.5">
                  <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/80">
                    <span>Pathfinder</span>
                    <ChevronRight className="h-3 w-3" />
                    <span className="truncate">{meta.title}</span>
                  </div>
                  <div className="flex min-w-0 items-center gap-2">
                    <h1 className="truncate text-[15px] font-semibold tracking-tight md:text-base">{meta.title}</h1>
                    {!isChatRoute && (
                      <p className="hidden truncate text-xs text-muted-foreground lg:block">{meta.description}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <div className="hidden items-center gap-2 rounded-full border bg-card px-2 py-1 pr-2.5 md:flex">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                    {profileInitial}
                  </div>
                  <div className="min-w-0">
                    <p className="max-w-[140px] truncate text-xs font-medium text-foreground">
                      {activeProfile?.name || 'Student'}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    createSession();
                    navigate('/chat');
                  }}
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition-opacity hover:opacity-90"
                >
                  <MessageSquarePlus className="h-4 w-4" />
                  <span className="hidden sm:inline">New Chat</span>
                </button>
              </div>
            </div>
            {state.isStreaming && (
              <div className="flex items-center gap-2 border-t border-border/60 bg-primary/[0.03] px-4 py-1.5 text-[11px] text-muted-foreground md:px-5">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span className="truncate">Reviewing your profile, evidence, and relevant context…</span>
              </div>
            )}
          </header>
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/profile/conflicts" element={<ProfileConflictsPage />} />
            <Route path="/plans" element={<PlansPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
        </div>
    </ErrorBoundary>
  );
}
