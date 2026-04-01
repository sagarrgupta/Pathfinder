import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, Sparkles, ShieldAlert } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { getProfile, getProfileConflicts, resolveConflictChoice, selfResolveProfileConflicts } from '@/services/api';
import { cn } from '@/lib/utils';

function SectionCard({ className, children }) {
  return <div className={cn('rounded-2xl border bg-card shadow-sm', className)}>{children}</div>;
}

export default function ProfileConflictsPage() {
  const navigate = useNavigate();
  const { state, dispatch } = useApp();
  const toast = useToast();
  const studentId = state.activeStudentId;
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [resolvingId, setResolvingId] = useState('');
  const [selfResolving, setSelfResolving] = useState(false);
  const [selectedOptions, setSelectedOptions] = useState({});

  useEffect(() => {
    if (!studentId) return;
    void loadConflicts();
  }, [studentId]);

  async function loadConflicts() {
    setLoading(true);
    try {
      const data = await getProfileConflicts(studentId);
      setItems(data);
      setSelectedOptions(
        Object.fromEntries(
          data.map((item) => [
            item.id,
            item.options?.[0]?.label || '',
          ]),
        ),
      );
    } catch (err) {
      toast.error(`Failed to load conflicts: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleResolve(item) {
    const selectedLabel = selectedOptions[item.id];
    const selectedOption = (item.options || []).find((option) => option.label === selectedLabel) || item.options?.[0];
    if (!selectedOption) return;

    setResolvingId(item.id);
    try {
      await resolveConflictChoice({
        student_id: studentId,
        conflict_id: item.id,
        fact_type: item.fact_type,
        action: selectedOption.action,
        selected_value: selectedOption.value || null,
      });
      const profile = await getProfile(studentId);
      dispatch({ type: 'SET_PROFILE', payload: profile });
      toast.success('Conflict updated');
      await loadConflicts();
    } catch (err) {
      toast.error(`Could not resolve conflict: ${err.message}`);
    } finally {
      setResolvingId('');
    }
  }

  async function handleSelfResolve() {
    setSelfResolving(true);
    try {
      const result = await selfResolveProfileConflicts(studentId);
      const profile = await getProfile(studentId);
      dispatch({ type: 'SET_PROFILE', payload: profile });
      if ((result.resolved_count || 0) > 0 && (result.remaining_conflicts || 0) > 0) {
        toast.success(`Resolved ${result.resolved_count} conflict(s). ${result.remaining_conflicts} still need your input.`);
      } else if ((result.resolved_count || 0) > 0) {
        toast.success(`Resolved ${result.resolved_count} conflict(s) automatically.`);
      } else {
        toast.info(`Nothing safe to resolve automatically. ${result.remaining_conflicts || 0} still need your input.`);
      }
      await loadConflicts();
    } catch (err) {
      toast.error(`Could not self-resolve conflicts: ${err.message}`);
    } finally {
      setSelfResolving(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="mx-auto max-w-4xl space-y-6 p-6 animate-fade-in">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-1">
            <button
              onClick={() => navigate('/profile')}
              className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to profile
            </button>
            <h1 className="text-2xl font-bold tracking-tight">Resolve conflicts</h1>
            <p className="text-sm text-muted-foreground">
              Review conflicting profile signals and choose what Pathfinder should treat as current.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {items.length > 0 && (
              <button
                onClick={handleSelfResolve}
                disabled={selfResolving}
                className="inline-flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
              >
                {selfResolving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4 text-primary" />}
                Self-resolve
              </button>
            )}
            <div className="rounded-full border bg-card px-3 py-1.5 text-sm font-medium text-muted-foreground">
              {items.length} open
            </div>
          </div>
        </div>

        {loading ? (
          <SectionCard className="flex items-center gap-3 p-5 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading conflicts...
          </SectionCard>
        ) : items.length === 0 ? (
          <SectionCard className="p-8 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <h2 className="text-base font-semibold tracking-tight">No unresolved conflicts</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Your profile memory looks consistent right now.
            </p>
          </SectionCard>
        ) : (
          <div className="space-y-4">
            {items.map((item) => (
              <SectionCard key={item.id} className="p-5">
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1">
                      <div className="inline-flex items-center gap-2 rounded-full bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                        <ShieldAlert className="h-3.5 w-3.5" />
                        {String(item.fact_type || '').replace(/_/g, ' ')}
                      </div>
                      <h2 className="text-base font-semibold tracking-tight">{item.question}</h2>
                      <p className="text-sm text-muted-foreground">{item.message}</p>
                    </div>
                    <div className="rounded-full border bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground">
                      {Math.round((item.confidence || 0) * 100)}% confidence
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl border border-primary/15 bg-primary/5 p-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Current option</p>
                      <p className="mt-2 text-sm font-medium text-foreground">{item.current_option}</p>
                    </div>
                    <div className="rounded-2xl border bg-muted/25 p-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Other option{(item.other_options || []).length === 1 ? '' : 's'}</p>
                      <div className="mt-2 space-y-2">
                        {(item.other_options || []).length > 0 ? (item.other_options || []).map((option) => (
                          <p key={option} className="text-sm text-foreground">{option}</p>
                        )) : (
                          <p className="text-sm text-muted-foreground">No alternate option available.</p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">What should Pathfinder do?</label>
                    <select
                      value={selectedOptions[item.id] || ''}
                      onChange={(event) => setSelectedOptions((current) => ({ ...current, [item.id]: event.target.value }))}
                      className="w-full rounded-xl border bg-background px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
                    >
                      {(item.options || []).map((option) => (
                        <option key={`${item.id}-${option.label}`} value={option.label}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex items-start gap-2 rounded-xl border border-border/70 bg-muted/20 px-3 py-2.5 text-sm text-muted-foreground">
                    <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
                    <p>
                      Your choice updates what Pathfinder treats as current in future recommendations. You can still change it later.
                    </p>
                  </div>

                  <div className="flex justify-end">
                    <button
                      onClick={() => handleResolve(item)}
                      disabled={resolvingId === item.id}
                      className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {resolvingId === item.id ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      Apply choice
                    </button>
                  </div>
                </div>
              </SectionCard>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
