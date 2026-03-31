import React, { useEffect, useMemo, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { getHealth } from '@/services/api';
import { Activity, ChevronDown, ChevronUp, Loader2, HeartPulse, Route, Database, Globe } from 'lucide-react';

function toSentenceCase(value) {
  if (value == null) return 'Unknown';
  const text = String(value).trim();
  if (!text) return 'Unknown';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatDebugValue(value) {
  if (value == null || value === '') return 'None';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString([], {
        dateStyle: 'medium',
        timeStyle: 'short',
      });
    }
  }
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'None';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function prettifyPlannerStep(step) {
  const text = String(step || '').trim();
  if (!text) return { label: 'Unknown step', detail: '' };
  if (text.startsWith('triage:')) {
    const [, intent = '', task = '', depth = ''] = text.split(':');
    return {
      label: 'Question classified',
      detail: [intent, task, depth].filter(Boolean).map(toSentenceCase).join(' • '),
    };
  }
  if (text.startsWith('planner:')) {
    const path = text.replace(/^planner:/, '').split('->').map((part) => toSentenceCase(part.replace(/_/g, ' ')));
    return {
      label: 'Selected path',
      detail: path.join(' -> '),
    };
  }
  return {
    label: toSentenceCase(text.replace(/_/g, ' ')),
    detail: '',
  };
}

export default function AnalyticsPage() {
  const { state } = useApp();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await getHealth();
        setHealth(data);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const latestAssistantMessage = useMemo(() => {
    const messages = state.activeSessionId ? state.messagesBySession[state.activeSessionId] || [] : [];
    return [...messages].reverse().find((msg) => msg.role === 'assistant') || null;
  }, [state.activeSessionId, state.messagesBySession]);

  const metadata = latestAssistantMessage?.metadata || {};

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Loading analytics…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-3xl mx-auto p-6 space-y-6 animate-fade-in">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
            <Activity className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
            <p className="text-muted-foreground text-sm mt-0.5">Lightweight system health and the latest runtime summary.</p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <MetricCard label="Runtime Status" value={toSentenceCase(health?.status || 'unknown')} icon={HeartPulse} />
          <MetricCard label="Background Jobs" value={toSentenceCase(health?.background_jobs?.active_task ? 'running' : 'idle')} icon={Database} />
          <MetricCard label="Planner Steps" value={`${metadata.plannerTrace?.length || 0}`} icon={Route} />
        </div>

        <section className="rounded-2xl border bg-card p-5 space-y-4">
          <div>
            <h2 className="font-semibold">Latest Retrieval Summary</h2>
            <p className="text-sm text-muted-foreground">A quick view of what Pathfinder actually used in the latest answer.</p>
          </div>
          {metadata.retrievalSummary ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 text-sm">
              <SmallStat label="Facts" value={metadata.retrievalSummary.candidate_facts || 0} />
              <SmallStat label="Memories" value={metadata.retrievalSummary.memory_items || 0} />
              <SmallStat label="Docs" value={metadata.retrievalSummary.documents || 0} />
              <SmallStat label="Web" value={metadata.retrievalSummary.web_results || 0} />
            </div>
          ) : (
            <div className="rounded-xl border border-dashed bg-muted/20 px-4 py-5 text-sm text-muted-foreground">
              No retrieval summary available yet. Ask a question in chat to generate a runtime snapshot.
            </div>
          )}
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-2xl border bg-card p-5">
            <div>
              <h2 className="font-semibold">Latest Runtime Path</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The latest route Pathfinder took to answer the current profile’s question.
              </p>
            </div>
            {metadata.plannerTrace?.length ? (
              <div className="mt-4 space-y-2">
                {metadata.plannerTrace.map((step, index) => {
                  const item = prettifyPlannerStep(step);
                  return (
                    <div
                      key={`${step}-${index}`}
                      className="rounded-xl border border-border/70 bg-muted/25 px-3.5 py-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">{item.label}</p>
                          {item.detail ? (
                            <p className="mt-1 text-sm text-muted-foreground break-words">{item.detail}</p>
                          ) : null}
                        </div>
                        <span className="shrink-0 rounded-full bg-background px-2 py-0.5 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                          Step {index + 1}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">No planner trace available yet for this profile.</p>
            )}
          </div>

          <div className="rounded-2xl border bg-card p-5">
            <h2 className="font-semibold">Health Snapshot</h2>
            <div className="mt-3 space-y-2 text-sm">
              <HealthRow label="Neo4j" value={toSentenceCase(health?.neo4j)} />
              <HealthRow label="LM Studio" value={toSentenceCase(health?.lm_studio)} />
              <HealthRow label="Ollama" value={toSentenceCase(health?.ollama)} />
              <HealthRow label="Web support" value={toSentenceCase(metadata.retrievalSummary?.web_results ? 'used' : 'not used')} icon={Globe} />
            </div>
          </div>
        </section>

        <section className="rounded-2xl border bg-card p-5 space-y-3">
          <button
            onClick={() => setShowDebug(!showDebug)}
            className="flex w-full items-center justify-between text-left"
          >
            <div>
              <h2 className="font-semibold">Debug Details</h2>
              <p className="text-sm text-muted-foreground">Open only when you need execution traces and raw background-job info.</p>
            </div>
            {showDebug ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>

          {showDebug && (
            <div className="space-y-4 pt-2">
              <div>
                <h3 className="text-sm font-medium mb-2">Latest Execution Trace</h3>
                {metadata.executionTrace?.length ? (
                  <div className="space-y-3">
                    {metadata.executionTrace.map((item, index) => (
                      <div key={index} className="rounded-xl border bg-muted/20 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <h4 className="text-sm font-medium">{toSentenceCase(item.agent || `Step ${index + 1}`)}</h4>
                          <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Step {index + 1}</span>
                        </div>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2">
                          {Object.entries(item)
                            .filter(([key]) => key !== 'agent')
                            .map(([key, value]) => (
                              <div key={key} className="rounded-lg bg-background px-3 py-2">
                                <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                                  {toSentenceCase(key.replace(/_/g, ' '))}
                                </p>
                                <p className="mt-1 text-sm text-foreground break-words">{formatDebugValue(value)}</p>
                              </div>
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No execution trace recorded yet.</p>
                )}
              </div>

              <div>
                <h3 className="text-sm font-medium mb-2">Background Consolidation</h3>
                {health?.background_jobs ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(health.background_jobs).map(([key, value]) => (
                      <div key={key} className="rounded-lg bg-muted/35 px-3 py-2">
                        <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                          {toSentenceCase(key.replace(/_/g, ' '))}
                        </p>
                        <p className="mt-1 text-sm font-medium text-foreground break-words">{formatDebugValue(value)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">Background job info unavailable.</p>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function MetricCard({ label, value, icon: Icon }) {
  return (
    <div className="rounded-2xl border bg-card p-4">
      <div className="flex items-center gap-2">
        {Icon ? <Icon className="h-4 w-4 text-primary" /> : null}
        <p className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">{label}</p>
      </div>
      <p className="mt-2 text-lg font-bold tracking-tight">{value}</p>
    </div>
  );
}

function SmallStat({ label, value }) {
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2">
      <p className="text-[11px] uppercase tracking-widest text-muted-foreground font-semibold">{label}</p>
      <p className="text-lg font-bold tracking-tight">{value}</p>
    </div>
  );
}

function HealthRow({ label, value, icon: Icon }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-muted/35 px-3 py-2">
      <div className="flex items-center gap-2">
        {Icon ? <Icon className="h-3.5 w-3.5 text-muted-foreground" /> : null}
        <span className="text-muted-foreground">{label}</span>
      </div>
      <span className="font-medium capitalize">{value || 'unknown'}</span>
    </div>
  );
}
