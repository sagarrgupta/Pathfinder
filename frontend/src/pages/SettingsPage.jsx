import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { getSettings, updateSettings, getHealth, resetStudentData, deleteAllDataEverywhere, deleteStudentProfile } from '@/services/api';
import {
  Settings, Shield, Monitor, Server, Loader2,
  Trash2, AlertTriangle, X,
  Sun, Moon, SunMoon, Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const MODEL_KEY_LABELS = {
  text_llm: 'Text LLM',
  vision_llm: 'Vision LLM',
  embeddings: 'Embeddings',
};

function formatModelKey(key) {
  return MODEL_KEY_LABELS[key] || key.replace(/_/g, ' ');
}

/** Matches backend health: e.g. web_search is "configured" when keys are set, not "connected". */
function isDependencyHealthy(status) {
  return status === 'connected' || status === 'configured' || status === 'fallback_only';
}

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: SunMoon },
];

const REASONING_OPTIONS = [
  { value: 'off', label: 'Off' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

export default function SettingsPage() {
  const { state, dispatch, refreshStudent, refreshStudents } = useApp();
  const toast = useToast();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [showResetModal, setShowResetModal] = useState(false);
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
  const [studentToDelete, setStudentToDelete] = useState(null);
  const activeStudent = state.students.find((student) => student.student_id === state.activeStudentId);
  const modelEntries = Object.entries(state.settings.models || {});
  const dependencyPairs = health?.services
    ? Object.entries(health.services).map(([key, status]) => [
        key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
        status,
      ])
    : [];

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

  const handleReasoning = async (newValue) => {
    const previous = state.settings.reasoning || 'medium';
    dispatch({ type: 'SET_SETTINGS', payload: { reasoning: newValue } });
    try {
      await updateSettings({ reasoning: newValue });
      toast.success('Reasoning level updated');
    } catch {
      dispatch({ type: 'SET_SETTINGS', payload: { reasoning: previous } });
      toast.error('Failed to update reasoning level');
    }
  };

  const handleProvider = async (provider) => {
    if (provider === state.settings.llm_provider || switchingProvider) return;
    setSwitchingProvider(true);
    try {
      const updated = await updateSettings({ llm_provider: provider });
      dispatch({ type: 'SET_SETTINGS', payload: updated });
      setHealth(null);
      toast.success(`Switched to ${provider === 'nvidia' ? 'NVIDIA' : 'LM Studio'}`);
      const healthData = await getHealth().catch(() => null);
      setHealth(healthData);
    } catch (error) {
      toast.error(error.message || 'Failed to switch model provider');
    } finally {
      setSwitchingProvider(false);
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
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto scrollbar-fade">
      <div className="mx-auto max-w-4xl space-y-6 p-6 animate-fade-in">
        {/* Header */}
        <div className="hero-panel px-6 py-7 sm:px-8">
          <div className="mb-3 eyebrow">Product settings</div>
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary/20 via-primary/10 to-warning/15 ring-1 ring-primary/15">
              <Settings className="h-7 w-7 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
              <p className="mt-0.5 text-sm text-muted-foreground">Control how Pathfinder looks, reasons, and connects to its services.</p>
            </div>
          </div>
          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="metric-tile">
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Text Model</p>
              <p className="mt-3 line-clamp-2 text-sm font-medium">{state.settings.models?.text_llm || 'Unknown'}</p>
            </div>
            <div className="metric-tile">
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Retrieval</p>
              <p className="mt-3 text-sm font-medium">{state.settings.models?.retrieval || 'Unknown'}</p>
            </div>
          </div>
        </div>

        {/* Appearance */}
        <div className="section-card">
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
        <div className="section-card">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <Shield className="h-4 w-4 text-primary" /> Guardrails
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Input Guard</p>
              <p className="text-xs text-muted-foreground">
                When enabled, Pathfinder blocks obviously unsafe SQL-injection-style input patterns.
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
          <div className="flex items-center justify-between mt-4 pt-4 border-t border-border/50">
            <div>
              <p className="text-sm font-medium">Reasoning Level</p>
              <p className="text-xs text-muted-foreground">
                Choose how much reasoning effort Pathfinder should request from the selected model.
              </p>
            </div>
            <select
              value={state.settings.reasoning || 'medium'}
              onChange={(e) => handleReasoning(e.target.value)}
              className="h-10 rounded-lg border border-border bg-background px-3 text-sm"
            >
              {REASONING_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Models */}
        <div className="section-card">
          <h2 className="font-semibold flex items-center gap-2 mb-4">
            <Monitor className="h-4 w-4 text-primary" /> Models
          </h2>
          <div className="flex flex-col gap-3 border-b border-border/50 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <label htmlFor="llm-provider" className="text-sm font-medium">Model provider</label>
              <p id="llm-provider-description" className="mt-1 text-xs text-muted-foreground">
                LM Studio runs on this computer. NVIDIA uses hosted models.
                {' '}Your selection is saved for future sessions.
              </p>
              {!state.settings.nvidia_configured && (
                <p className="mt-1 text-xs text-muted-foreground">Set up an NVIDIA API key on the backend to enable NVIDIA.</p>
              )}
              {state.isStreaming && (
                <p className="mt-1 text-xs text-muted-foreground">Wait for the current response to finish before switching.</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2" aria-busy={switchingProvider}>
              {switchingProvider && <Loader2 className="h-4 w-4 animate-spin text-primary" aria-label="Switching provider" />}
              <select
                id="llm-provider"
                aria-describedby="llm-provider-description"
                value={state.settings.llm_provider || 'lmstudio'}
                onChange={(e) => handleProvider(e.target.value)}
                disabled={switchingProvider || state.isStreaming}
                className="h-10 rounded-lg border border-border bg-background px-3 text-sm disabled:opacity-50"
              >
                <option value="lmstudio">LM Studio (local)</option>
                <option value="nvidia" disabled={!state.settings.nvidia_configured}>NVIDIA (hosted)</option>
              </select>
            </div>
          </div>
          <div className="space-y-0">
            {modelEntries.map(([key, value]) => (
              <div key={key} className="flex justify-between items-center py-3 border-b last:border-0 border-border/50">
                <span className="text-sm text-muted-foreground">{formatModelKey(key)}</span>
                <code className="text-sm font-mono bg-muted px-2.5 py-1 rounded-md">{value}</code>
              </div>
            ))}
          </div>
        </div>

        {(health || modelEntries.length > 0) && (
          <div className="section-card">
            <h2 className="font-semibold flex items-center gap-2 mb-4">
              <Zap className="h-4 w-4 text-primary" /> Runtime
            </h2>
            <div className="grid grid-cols-1 gap-3 mb-4 sm:grid-cols-2">
              <div className="metric-tile">
                <p className="text-xs text-muted-foreground mb-1">Retrieval Mode</p>
                <p className="text-sm font-medium">{state.settings.models?.retrieval || 'Unknown'}</p>
              </div>
              <div className="metric-tile">
                <p className="text-xs text-muted-foreground mb-1">Active Text Model</p>
                <p className="text-sm font-medium break-words">{state.settings.models?.text_llm || 'Unknown'}</p>
              </div>
            </div>
            {dependencyPairs.length > 0 && (
              <div className="space-y-2">
                {dependencyPairs.map(([name, status]) => (
                  <div key={name} className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-3.5 py-3 text-sm shadow-sm">
                    <div>
                      <p className="font-medium">{name}</p>
                      <p className="text-xs text-muted-foreground">Runtime dependency</p>
                    </div>
                    <span className={cn(
                      'rounded-full px-2.5 py-1 text-xs font-semibold',
                      isDependencyHealthy(status)
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                    )}>
                      {status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* System Health */}
        {health && (
          <div className="section-card">
            <h2 className="font-semibold flex items-center gap-2 mb-4">
              <Server className="h-4 w-4 text-primary" /> System Health
            </h2>
            <div className="space-y-0">
              {dependencyPairs.map(([name, status]) => (
                <div key={name} className="flex items-center justify-between border-b border-border/50 py-3 last:border-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{name}</span>
                    {name === 'Neo4j' && (
                      <a
                        href="http://localhost:7474/browser/"
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-medium text-primary hover:underline"
                        title="Open Neo4j Browser"
                      >
                        Open panel
                      </a>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {isDependencyHealthy(status) ? (
                      <>
                        {status === 'connected' ? (
                          <span className="relative flex h-2.5 w-2.5">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
                          </span>
                        ) : (
                          <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
                        )}
                        <span className="text-xs font-medium text-green-600 dark:text-green-400">
                          {status === 'configured' ? 'Configured' : 'Connected'}
                        </span>
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
        <div className="section-card">
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
              <span className="font-medium">Single-Specialist LangGraph + MCP Tools</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Features</span>
              <span className="font-medium">Personalized AI Guidance</span>
            </div>
          </div>
        </div>

        {/* Danger Zone */}
        <div className="rounded-[24px] border-2 border-destructive/20 bg-card/90 p-5 shadow-sm">
          <h2 className="font-semibold flex items-center gap-2 mb-4 text-destructive">
            <AlertTriangle className="h-4 w-4" /> Danger Zone
          </h2>
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm font-medium">Reset All Data</p>
              <p className="text-xs text-muted-foreground">
                Permanently delete this student's documents, entities, and graph data.
              </p>
            </div>
            <button
              onClick={() => setShowResetModal(true)}
              disabled={!state.activeStudentId}
              className="px-4 py-2 text-sm rounded-lg border-2 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5 font-medium active:scale-95 disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Reset
            </button>
          </div>
          <div className="flex items-center justify-between py-4 border-t border-destructive/20 gap-4">
            <div>
              <p className="text-sm font-medium">Delete Student Profile</p>
              <p className="text-xs text-muted-foreground">
                Permanently delete {activeStudent?.name || 'the selected student'}'s profile, documents, and chats. Other students are kept.
              </p>
            </div>
            <button
              onClick={() => setStudentToDelete({ student_id: state.activeStudentId, name: activeStudent?.name || 'this student' })}
              disabled={!state.activeStudentId || state.isStreaming || state.studentLoading}
              className="px-4 py-2 text-sm rounded-lg border-2 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5 font-medium active:scale-95 disabled:opacity-40 disabled:pointer-events-none shrink-0"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete Profile
            </button>
          </div>
          <div className="flex items-center justify-between pt-4 border-t border-destructive/20">
            <div>
              <p className="text-sm font-medium">Delete All Data (All Students)</p>
              <p className="text-xs text-muted-foreground">
                Permanently delete every student, all Neo4j graph data, and all chat history.
              </p>
            </div>
            <button
              onClick={() => setShowDeleteAllModal(true)}
              className="px-4 py-2 text-sm rounded-lg border-2 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5 font-medium active:scale-95"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete All
            </button>
          </div>
        </div>
      </div>

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <ResetModal
          studentId={state.activeStudentId}
          onClose={() => setShowResetModal(false)}
          onSuccess={async (msg) => {
            dispatch({ type: 'CLEAR_STUDENT_DATA', payload: state.activeStudentId });
            await refreshStudents().catch(() => {});
            await refreshStudent(state.activeStudentId).catch(() => {});
            toast.success(msg);
          }}
        />
      )}

      {studentToDelete && (
        <DeleteProfileModal
          student={studentToDelete}
          onClose={() => setStudentToDelete(null)}
          onSuccess={() => {
            dispatch({ type: 'REMOVE_STUDENT', payload: studentToDelete.student_id });
            toast.success('Student profile and associated data deleted.');
          }}
        />
      )}

      {showDeleteAllModal && (
        <DeleteAllModal
          onClose={() => setShowDeleteAllModal(false)}
          onSuccess={async (msg) => {
            dispatch({ type: 'CLEAR_ALL_LOCAL_DATA' });
            await refreshStudents().catch(() => {});
            toast.success(msg);
          }}
        />
      )}
    </div>
  );
}

// ── Reset Confirmation Modal ────────────────────────────────────

function ResetModal({ studentId, onClose, onSuccess }) {
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState('');

  const handleReset = async () => {
    setIsResetting(true);
    setError('');
    try {
      await resetStudentData(studentId);
      onSuccess('All student data has been reset successfully.');
      onClose();
    } catch (err) {
      setError(`Reset failed: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <DangerModal
      title="Reset All Data"
      intro={(
        <>
          This action will <strong className="text-destructive">permanently delete</strong> all of the following:
        </>
      )}
      items={[
        'This student node and its stored properties',
        'All uploaded documents and extracted text',
        'All sections, entities, fields, and relationships',
        'The complete student graph for this student id',
      ]}
      error={error}
      isSubmitting={isResetting}
      confirmLabel="Yes"
      pendingLabel="Deleting..."
      onClose={onClose}
      onConfirm={handleReset}
    />
  );
}

function DeleteProfileModal({ student, onClose, onSuccess }) {
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');

  const handleDelete = async () => {
    setIsDeleting(true);
    setError('');
    try {
      await deleteStudentProfile(student.student_id);
      onSuccess();
      onClose();
    } catch (err) {
      setError(`Delete failed: ${err.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <DangerModal
      title="Delete Student Profile"
      intro={<>Permanently delete <strong className="text-destructive">{student.name}</strong> and their associated data? Other student profiles will be kept.</>}
      items={[
        'The student profile and its stored properties',
        'All of their documents, extracted data, and graph',
        'All of their chats and replay artifacts',
      ]}
      error={error}
      isSubmitting={isDeleting}
      confirmLabel="Yes, Delete Profile"
      pendingLabel="Deleting..."
      onClose={onClose}
      onConfirm={handleDelete}
    />
  );
}

function DeleteAllModal({ onClose, onSuccess }) {
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');

  const handleDeleteAll = async () => {
    setIsDeleting(true);
    setError('');
    try {
      await deleteAllDataEverywhere();
      onSuccess('All students, graph data, and chats have been deleted.');
      onClose();
    } catch (err) {
      setError(`Delete all failed: ${err.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <DangerModal
      title="Delete All Data"
      intro={(
        <>
          This will permanently delete <strong className="text-destructive">everything for all students</strong>:
        </>
      )}
      items={[
        'All student records',
        'All Neo4j nodes and relationships',
        'All persisted chat history',
        'All uploaded documents and extracted entities',
      ]}
      error={error}
      isSubmitting={isDeleting}
      confirmLabel="Yes, Delete All"
      pendingLabel="Deleting..."
      onClose={onClose}
      onConfirm={handleDeleteAll}
    />
  );
}

function DangerModal({
  title,
  intro,
  items,
  error,
  isSubmitting,
  confirmLabel,
  pendingLabel,
  onClose,
  onConfirm,
}) {
  const backdropRef = useRef(null);

  const handleBackdropClick = (e) => {
    if (!isSubmitting && e.target === backdropRef.current) onClose();
  };

  useEffect(() => {
    const handleKey = (e) => { if (!isSubmitting && e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose, isSubmitting]);

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in"
    >
      <div className="hero-panel mx-4 w-full max-w-md animate-fade-in-up border-destructive/20">
        <div className="flex items-center justify-between p-5 pb-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-destructive/15 to-destructive/5 ring-1 ring-destructive/20">
              <AlertTriangle className="h-5 w-5 text-destructive" />
            </div>
            <div>
              <p className="eyebrow mb-1 text-destructive/80">Danger zone</p>
              <h3 className="text-lg font-bold">{title}</h3>
            </div>
          </div>
          <button onClick={onClose} disabled={isSubmitting} className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-sm text-muted-foreground leading-relaxed">{intro}</p>
          <ul className="space-y-2 rounded-2xl border border-destructive/15 bg-background/75 p-3 text-sm">
            {items.map((text, i) => (
              <li key={i} className="flex items-center gap-2.5 text-muted-foreground">
                <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-destructive" />
                {text}
              </li>
            ))}
          </ul>
          <div className="rounded-2xl border border-destructive/20 bg-destructive/5 p-3">
            <p className="text-xs text-destructive font-medium flex items-center gap-1.5">
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
              This action cannot be undone.
            </p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 p-5 pt-0">
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="px-4 py-2.5 text-sm rounded-lg border hover:bg-accent transition-colors font-medium"
          >
            No
          </button>
          <button
            onClick={onConfirm}
            disabled={isSubmitting}
            className="px-4 py-2.5 text-sm rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-40 transition-all flex items-center gap-1.5 font-medium active:scale-95"
          >
            {isSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            {isSubmitting ? pendingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
