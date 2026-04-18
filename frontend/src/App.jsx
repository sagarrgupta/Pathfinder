import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useApp } from './context/AppContext';
import Sidebar from './components/layout/Sidebar';
import ChatPage from './pages/ChatPage';
import ProfilePage from './pages/ProfilePage';
import ReplayPage from './pages/ReplayPage';
import SettingsPage from './pages/SettingsPage';
import ErrorBoundary from './components/shared/ErrorBoundary';

export default function App() {
  const { state, dispatch } = useApp();

  return (
    <ErrorBoundary>
      <div className="app-shell flex h-screen overflow-hidden bg-background px-3 py-3 md:px-4 md:py-4">
        {/* Sidebar */}
        <Sidebar
          open={state.sidebarOpen}
          onToggle={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
        />

        {/* Main Content */}
        <main className="relative ml-3 flex min-w-0 min-h-0 flex-1 flex-col overflow-hidden">
          <div className="page-surface flex min-h-0 flex-1 flex-col overflow-hidden">
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/student" element={<ProfilePage />} />
              <Route path="/replays" element={<ReplayPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </main>
        </div>
    </ErrorBoundary>
  );
}
