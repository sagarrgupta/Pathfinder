import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { getSettings, updateSettings, getHealth, resetAllData, compareRetrieval } from '@/services/api';
import {
  Settings, Shield, Monitor, Server, Loader2,
  CheckCircle2, XCircle, Trash2, AlertTriangle, X,
  Sun, Moon, SunMoon, Zap, Search,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const MODEL_KEY_LABELS = {
  text_llm: 'Text LLM',
  vision_llm: 'Vision LLM',
  embeddings: 'Embedding',
};

function formatModelKey(key) {
  return MODEL_KEY_LABELS[key] || key.replace(/_/g, ' ');
}

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: SunMoon },
];

const RETRIEVAL_MODES = [
  { value: 'embedding', label: 'Embedding Only', description: 'Pure semantic vector retrieval over document chunks.' },
  { value: 'hybrid', label: 'Hybrid (Graph + Embedding)', description: 'Neo4j vector retrieval enriched with graph context.' },
  { value: 'pageindex', label: 'PageIndex + Graph', description: 'PageIndex page selection with Neo4j profile context and normal web research routing.' },
];

export default function SettingsPage() {
  const { state, dispatch } = useApp();
  const toast = useToast();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showResetModal, setShowResetModal] = useState(false);
  const [compareQuery, setCompareQuery] = useState('');
  const [compareLoading, setCompareLoading] = useState(false);
  const [comparison, setComparison] = useState(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [settingsData, healthData] = await Promise.all([
        getSettings().catch(() => null),
        getHealth().catch(() => null),
      ]);
      if (settingsData) dispatch({ type: 'SET_SETTINGS', payload: settingsData });
      if (healthData) setHealth(healthData);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleGuard = async () => {
    const newValue = !state.settings.topic_guard_enabled;
    dispatch({ type: 'SET_SETTINGS', payload: { topic_guard_enabled: newValue } });
    try {
      await updateSettings({ topic_guard_enabled: newValue });
      toast.success(newValue ? 'Topic guard enabled' : 'Topic guard disabled');
    } catch {
      dispatch({ type: 'SET_SETTINGS', payload: { topic_guard_enabled: !newValue } });
      toast.error('Failed to update setting');
    }
  };

  const handleRetrievalModeChange = async (event) => {
    const newValue = event.target.value;
    const previous = state.settings.retrieval_mode;
    dispatch({ type: 'SET_SETTINGS', payload: { retrieval_mode: newValue } });
    try {
      await updateSettings({ retrieval_mode: newValue });
      toast.success('Retrieval mode updated');
    } catch {
      dispatch({ type: 'SET_SETTINGS', payload: { retrieval_mode: previous } });
      toast.error('Failed to update retrieval mode');
    }
  };

  const handleCompare = async () => {
    if (!compareQuery.trim()) {
      toast.error('Enter a query to benchmark retrieval');
      return;
    }
    setCompareLoading(true);
    try {
      const data = await compareRetrieval(compareQuery, state.activeSessionId);
      setComparison(data);
    } catch (error) {
      toast.error(error.message || 'Failed to compare retrieval modes');
    } finally {
      setCompareLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Loading settings…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-2xl mx-auto p-6 space-y-6 animate-fade-in">
        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
            <Settings className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
            <p className="text-muted-foreground text-sm mt-0.5">Configure Pathfinder behavior and appearance</p>
          </div>
        </div>

        {/* Appearance */}
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <SunMoon className="h-4 w-4 text-primary" /> Appearance
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Theme</p>
              <p className="text-xs text-muted-foreground">Select your preferred color scheme</p>
            </div>
            <div className="flex items-center gap-1 p-1 rounded-lg bg-muted">
              {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  onClick={() => dispatch({ type: 'SET_THEME', payload: value })}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all',
                    state.theme === value
                      ? 'bg-card text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                  title={label}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Guardrails */}
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <Shield className="h-4 w-4 text-primary" /> Guardrails
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Topic Guard</p>
              <p className="text-xs text-muted-foreground">
                When enabled, Pathfinder only responds to academic and career-related questions.
              </p>
            </div>
            <button
              onClick={handleToggleGuard}
              className={cn(
                'relative w-11 h-6 rounded-full transition-colors flex-shrink-0',
                state.settings.topic_guard_enabled ? 'bg-primary' : 'bg-muted-foreground/30'
              )}
            >
              <span className={cn(
                'block w-5 h-5 bg-white rounded-full shadow-md transition-transform absolute top-0.5 left-0.5',
                state.settings.topic_guard_enabled ? 'translate-x-5' : 'translate-x-0'
              )} />
            </button>
          </div>
        </div>

        <div className="rounded-xl border bg-card p-5 space-y-4">
          <h2 className="font-semibold flex items-center gap-2">
            <Search className="h-4 w-4 text-primary" /> Retrieval
          </h2>
          <div className="space-y-2">
            <div>
              <p className="text-sm font-medium">Active Retrieval Mode</p>
              <p className="text-xs text-muted-foreground">
                Choose which retrieval pipeline powers document lookup during chat.
              </p>
            </div>
            <select
              value={state.settings.retrieval_mode || 'hybrid'}
              onChange={handleRetrievalModeChange}
              className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
            >
              {RETRIEVAL_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              {(RETRIEVAL_MODES.find((mode) => mode.value === (state.settings.retrieval_mode || 'hybrid')) || RETRIEVAL_MODES[1]).description}
            </p>
          </div>

          <div className="pt-4 border-t border-border/50 space-y-3">
            <div>
              <p className="text-sm font-medium">Benchmark Retrieval Modes</p>
              <p className="text-xs text-muted-foreground">
                Run the same query through all three pipelines and compare latency and hit counts.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                value={compareQuery}
                onChange={(event) => setCompareQuery(event.target.value)}
                placeholder="Enter a test query"
                className="flex-1 rounded-lg border bg-background px-3 py-2 text-sm"
              />
              <button
                onClick={handleCompare}
                disabled={compareLoading}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
              >
                {compareLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Compare
              </button>
            </div>

            {comparison?.comparisons?.length > 0 && (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Mode</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                      <th className="px-3 py-2 text-left font-medium">Latency</th>
                      <th className="px-3 py-2 text-left font-medium">Hits</th>
                      <th className="px-3 py-2 text-left font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.comparisons.map((item) => (
                      <tr key={item.mode} className="border-t">
                        <td className="px-3 py-2 font-medium">{(RETRIEVAL_MODES.find((mode) => mode.value === item.mode) || { label: item.mode }).label}</td>
                        <td className="px-3 py-2">{item.ok ? 'OK' : 'Error'}</td>
                        <td className="px-3 py-2">{Math.round(item.stats?.elapsed_ms || 0)}ms</td>
                        <td className="px-3 py-2">{item.stats?.result_count || 0}</td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {item.ok
                            ? `${item.stats?.document_count || 0} docs`
                            : item.error}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Models */}
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <Monitor className="h-4 w-4 text-primary" /> Models
          </h2>
          <div className="space-y-0">
            {Object.entries(state.settings.models || {}).map(([key, value]) => (
              <div key={key} className="flex justify-between items-center py-3 border-b last:border-0 border-border/50">
                <span className="text-sm text-muted-foreground">{formatModelKey(key)}</span>
                <code className="text-sm font-mono bg-muted px-2.5 py-1 rounded-md">{value}</code>
              </div>
            ))}
          </div>
        </div>

        {/* System Health */}
        {health && (
          <div className="rounded-xl border bg-card p-5">
            <h2 className="font-semibold flex items-center gap-2 mb-4">
              <Server className="h-4 w-4 text-primary" /> System Health
            </h2>
            <div className="space-y-0">
              {[
                ['Neo4j', health.neo4j],
                ['LM Studio', health.lm_studio],
                ['Ollama', health.ollama],
              ].map(([name, status]) => (
                <div key={name} className="flex items-center justify-between py-3 border-b last:border-0 border-border/50">
                  <span className="text-sm font-medium">{name}</span>
                  <div className="flex items-center gap-2">
                    {status === 'connected' ? (
                      <>
                        <span className="relative flex h-2.5 w-2.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
                        </span>
                        <span className="text-xs font-medium text-green-600 dark:text-green-400">Connected</span>
                      </>
                    ) : (
                      <>
                        <span className="h-2.5 w-2.5 rounded-full bg-destructive" />
                        <span className="text-xs font-medium text-destructive">
                          {status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown'}
                        </span>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Version Info */}
        <div className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <Zap className="h-4 w-4 text-primary" /> About
          </h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Version</span>
              <span className="font-mono font-medium">2.1.0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Architecture</span>
              <span className="font-medium">Multi-Agent LangGraph + Neo4j KG</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Features</span>
              <span className="font-medium">Personalized AI Guidance</span>
            </div>
          </div>
        </div>

        {/* Danger Zone */}
        <div className="rounded-xl border-2 border-destructive/20 bg-card p-5">
          <h2 className="font-semibold flex items-center gap-2 mb-4 text-destructive">
            <AlertTriangle className="h-4 w-4" /> Danger Zone
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Reset All Data</p>
              <p className="text-xs text-muted-foreground">
                Permanently delete your profile, all documents, courses, skills, and knowledge graph data.
              </p>
            </div>
            <button
              onClick={() => setShowResetModal(true)}
              className="px-4 py-2 text-sm rounded-lg border-2 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5 font-medium active:scale-95"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Reset
            </button>
          </div>
        </div>
      </div>

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <ResetModal
          onClose={() => setShowResetModal(false)}
          onSuccess={(msg) => {
            toast.success(msg);
            dispatch({ type: 'SET_PROFILE', payload: null });
          }}
        />
      )}
    </div>
  );
}

// ── Reset Confirmation Modal ────────────────────────────────────

function ResetModal({ onClose, onSuccess }) {
  const [confirmText, setConfirmText] = useState('');
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState('');
  const backdropRef = useRef(null);
  const CONFIRM_PHRASE = 'DELETE';

  const canConfirm = confirmText === CONFIRM_PHRASE;

  const handleReset = async () => {
    if (!canConfirm) return;
    setIsResetting(true);
    setError('');
    try {
      await resetAllData();
      onSuccess('All profile data has been reset successfully.');
      onClose();
    } catch (err) {
      setError(`Reset failed: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  const handleBackdropClick = (e) => {
    if (e.target === backdropRef.current) onClose();
  };

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in"
    >
      <div className="bg-card border rounded-2xl shadow-2xl max-w-md w-full mx-4 animate-fade-in-up">
        {/* Header */}
        <div className="flex items-center justify-between p-5 pb-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center">
              <AlertTriangle className="h-5 w-5 text-destructive" />
            </div>
            <h3 className="text-lg font-bold">Reset All Data</h3>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          <p className="text-sm text-muted-foreground leading-relaxed">
            This action will <strong className="text-destructive">permanently delete</strong> all of the following:
          </p>

          <ul className="text-sm space-y-2 pl-1">
            {[
              'Your student profile and personal information',
              'All uploaded documents and extracted text',
              'Courses, skills, goals, experience, and other entities',
              'Entire knowledge graph data',
            ].map((text, i) => (
              <li key={i} className="flex items-center gap-2.5 text-muted-foreground">
                <span className="w-1.5 h-1.5 rounded-full bg-destructive flex-shrink-0" />
                {text}
              </li>
            ))}
          </ul>

          <div className="p-3 rounded-lg bg-destructive/5 border border-destructive/20">
            <p className="text-xs text-destructive font-medium flex items-center gap-1.5">
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
              This action cannot be undone.
            </p>
          </div>

          {/* Confirmation input */}
          <div>
            <label className="text-sm font-medium block mb-2">
              Type <code className="px-1.5 py-0.5 bg-muted rounded-md text-destructive font-bold">DELETE</code> to confirm
            </label>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type DELETE here"
              className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-destructive/40 transition-shadow"
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter' && canConfirm) handleReset(); }}
            />
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 p-5 pt-0">
          <button
            onClick={onClose}
            className="px-4 py-2.5 text-sm rounded-lg border hover:bg-accent transition-colors font-medium"
          >
            Cancel
          </button>
          <button
            onClick={handleReset}
            disabled={!canConfirm || isResetting}
            className="px-4 py-2.5 text-sm rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-40 transition-all flex items-center gap-1.5 font-medium active:scale-95"
          >
            {isResetting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            {isResetting ? 'Deleting...' : 'Delete Everything'}
          </button>
        </div>
      </div>
    </div>
  );
}
