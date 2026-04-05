import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import { evaluateRecentReplays, evaluateReplay, getEvalAnalytics, getEvalBenchmarks, getReplay, getReplays } from '@/services/api';
import {
  Clock3, RefreshCw, PlaySquare, Loader2, Shield,
  Sparkles, Search, ExternalLink, AlertTriangle, CheckCircle2, XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';

function useReplayQueryParam() {
  const location = useLocation();
  return useMemo(() => new URLSearchParams(location.search).get('replay') || '', [location.search]);
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatPriority(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

function getEvalBadgeClass(status) {
  if (status === 'pass') {
    return 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300';
  }
  if (status === 'fail') {
    return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
  }
  return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300';
}

export default function ReplayPage() {
  const { state } = useApp();
  const replayFromQuery = useReplayQueryParam();
  const [replays, setReplays] = useState([]);
  const [selectedReplayId, setSelectedReplayId] = useState('');
  const [selectedReplay, setSelectedReplay] = useState(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingEvalSummary, setLoadingEvalSummary] = useState(true);
  const [error, setError] = useState('');
  const [showCurrentStudentOnly, setShowCurrentStudentOnly] = useState(true);
  const [evaluationSummary, setEvaluationSummary] = useState(null);
  const [evaluationsById, setEvaluationsById] = useState({});
  const [selectedEvaluation, setSelectedEvaluation] = useState(null);
  const [benchmarkSets, setBenchmarkSets] = useState([]);
  const [evalAnalytics, setEvalAnalytics] = useState(null);

  const filteredReplays = useMemo(() => {
    if (!showCurrentStudentOnly || !state.activeStudentId) return replays;
    return replays.filter((item) => item.student_id === state.activeStudentId);
  }, [replays, showCurrentStudentOnly, state.activeStudentId]);

  useEffect(() => {
    void loadList();
  }, []);

  useEffect(() => {
    void loadEvaluationSummary(showCurrentStudentOnly ? state.activeStudentId : null);
  }, [showCurrentStudentOnly, state.activeStudentId]);

  useEffect(() => {
    void loadEvalAnalytics(showCurrentStudentOnly ? state.activeStudentId : null);
    void loadBenchmarks();
  }, [showCurrentStudentOnly, state.activeStudentId]);

  useEffect(() => {
    if (replayFromQuery) {
      setSelectedReplayId(replayFromQuery);
      void loadDetail(replayFromQuery);
    }
  }, [replayFromQuery]);

  useEffect(() => {
    if (replayFromQuery) return;
    if (!selectedReplayId && filteredReplays.length > 0) {
      const nextId = filteredReplays[0].id;
      setSelectedReplayId(nextId);
      void loadDetail(nextId);
    }
  }, [filteredReplays, selectedReplayId, replayFromQuery]);

  const loadList = async () => {
    setLoadingList(true);
    setError('');
    try {
      const data = await getReplays(40);
      setReplays(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load replay artifacts.');
    } finally {
      setLoadingList(false);
    }
  };

  const loadDetail = async (replayId) => {
    if (!replayId) return;
    setLoadingDetail(true);
    setError('');
    try {
      const data = await getReplay(replayId);
      setSelectedReplay(data);
      setSelectedReplayId(replayId);
      const evaluation = await evaluateReplay(replayId);
      setSelectedEvaluation(evaluation);
      setEvaluationsById((prev) => ({ ...prev, [replayId]: evaluation }));
    } catch (err) {
      setError(err.message || 'Failed to load replay artifact.');
    } finally {
      setLoadingDetail(false);
    }
  };

  const loadEvaluationSummary = async (studentId = null) => {
    setLoadingEvalSummary(true);
    try {
      const data = await evaluateRecentReplays(40, studentId);
      setEvaluationSummary(data?.summary || null);
      const nextMap = {};
      for (const item of data?.evaluations || []) {
        nextMap[item.replay_id] = item;
      }
      setEvaluationsById(nextMap);
    } catch (err) {
      setError(err.message || 'Failed to load replay evaluations.');
    } finally {
      setLoadingEvalSummary(false);
    }
  };

  const loadBenchmarks = async () => {
    try {
      const data = await getEvalBenchmarks();
      setBenchmarkSets(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load benchmark sets.');
    }
  };

  const loadEvalAnalytics = async (studentId = null) => {
    try {
      const data = await getEvalAnalytics(50, studentId);
      setEvalAnalytics(data || null);
    } catch (err) {
      setError(err.message || 'Failed to load evaluation analytics.');
    }
  };

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-7xl mx-auto p-6 space-y-6 animate-fade-in">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
              <PlaySquare className="h-7 w-7 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Replay Browser</h1>
              <p className="text-muted-foreground text-sm mt-0.5">
                Inspect saved advisory turns, runtime choices, and retrieval traces.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={showCurrentStudentOnly}
                onChange={(e) => setShowCurrentStudentOnly(e.target.checked)}
                className="rounded border-border"
              />
              Current profile only
            </label>
            <button
              onClick={() => {
                void loadList();
                void loadEvaluationSummary(showCurrentStudentOnly ? state.activeStudentId : null);
                void loadEvalAnalytics(showCurrentStudentOnly ? state.activeStudentId : null);
                void loadBenchmarks();
              }}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border bg-card hover:bg-accent/40 transition-colors text-sm font-medium"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          <div className="rounded-xl border bg-card p-4">
            <p className="text-xs text-muted-foreground mb-1">Evaluated Replays</p>
            <p className="text-2xl font-bold">{loadingEvalSummary ? '...' : evaluationSummary?.total ?? 0}</p>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <p className="text-xs text-muted-foreground mb-1">Average Score</p>
            <p className="text-2xl font-bold">{loadingEvalSummary ? '...' : formatPercent(evaluationSummary?.average_score ?? 0)}</p>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <p className="text-xs text-muted-foreground mb-1">Passing</p>
            <p className="text-2xl font-bold text-green-600 dark:text-green-400">{loadingEvalSummary ? '...' : evaluationSummary?.passed ?? 0}</p>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <p className="text-xs text-muted-foreground mb-1">Warnings / Fails</p>
            <p className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
              {loadingEvalSummary ? '...' : `${evaluationSummary?.warned ?? 0} / ${evaluationSummary?.failed ?? 0}`}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[1.2fr,1fr] gap-6">
          <section className="rounded-2xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-semibold">Benchmark Sets</p>
                <p className="text-xs text-muted-foreground">
                  {benchmarkSets.length} benchmark group{benchmarkSets.length === 1 ? '' : 's'}
                </p>
              </div>
              <Shield className="h-4 w-4 text-primary" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {benchmarkSets.map((item) => (
                <div key={item.id} className="rounded-xl border bg-muted/20 p-3">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <p className="font-medium">{item.title}</p>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                      {item.scenario_count} cases
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{item.description}</p>
                  {item.workflow && (
                    <p className="text-xs text-muted-foreground mt-2">Workflow: {formatPriority(item.workflow)}</p>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-semibold">Trend Summary</p>
                <p className="text-xs text-muted-foreground">Recent replay-score direction</p>
              </div>
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                  {formatPriority(evalAnalytics?.trend?.direction || 'flat')}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  Delta {formatPercent(evalAnalytics?.trend?.delta || 0)}
                </span>
              </div>
              <div className="rounded-xl border bg-muted/20 p-3">
                <div className="flex items-end gap-1 h-24">
                  {(evalAnalytics?.trend?.points || []).slice(-12).map((point) => (
                    <div key={point.id} className="flex-1 flex flex-col items-center gap-1">
                      <div
                        className="w-full rounded-t bg-primary/70 min-h-[4px]"
                        style={{ height: `${Math.max(4, Math.round((Number(point.score) || 0) * 80))}px` }}
                      />
                    </div>
                  ))}
                </div>
                {(!evalAnalytics?.trend?.points || evalAnalytics.trend.points.length === 0) && (
                  <p className="text-sm text-muted-foreground">Not enough replay history yet.</p>
                )}
              </div>
            </div>
          </section>
        </div>

        {evalAnalytics?.comparisons && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {[
              ['Workflow Comparison', evalAnalytics.comparisons.by_workflow || []],
              ['Method Comparison', evalAnalytics.comparisons.by_method || []],
              ['Model Comparison', evalAnalytics.comparisons.by_model || []],
              ['Retrieval Comparison', evalAnalytics.comparisons.by_retrieval_mode || []],
            ].map(([title, rows]) => (
              <section key={title} className="rounded-2xl border bg-card p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="font-semibold">{title}</p>
                  <Search className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="space-y-2">
                  {(rows || []).slice(0, 6).map((row) => (
                    <div key={row.key} className="rounded-xl border bg-muted/20 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{formatPriority(row.key)}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                          {formatPercent(row.average_score)}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        {row.count} replays, {row.passed} pass, {row.warned} warn, {row.failed} fail
                      </p>
                    </div>
                  ))}
                  {(rows || []).length === 0 && (
                    <p className="text-sm text-muted-foreground">No replay comparisons available yet.</p>
                  )}
                </div>
              </section>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-[360px,minmax(0,1fr)] gap-6">
          <section className="rounded-2xl border bg-card overflow-hidden min-h-[520px]">
            <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
              <div>
                <p className="font-semibold">Saved Replays</p>
                <p className="text-xs text-muted-foreground">
                  {filteredReplays.length} artifact{filteredReplays.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>

            <div className="max-h-[70vh] overflow-y-auto">
              {loadingList ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground text-sm gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading replay artifacts…
                </div>
              ) : filteredReplays.length === 0 ? (
                <div className="py-14 px-6 text-center text-sm text-muted-foreground">
                  <Search className="h-5 w-5 mx-auto mb-2 opacity-70" />
                  No replay artifacts found yet.
                </div>
              ) : (
                <div className="p-2 space-y-2">
                  {filteredReplays.map((item) => {
                    const isActive = item.id === selectedReplayId;
                    const evaluation = evaluationsById[item.id];
                    return (
                      <button
                        key={item.id}
                        onClick={() => void loadDetail(item.id)}
                        className={cn(
                          'w-full text-left rounded-xl border px-3 py-3 transition-colors',
                          isActive
                            ? 'border-primary/30 bg-primary/5'
                            : 'border-border bg-card hover:bg-accent/30'
                        )}
                      >
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <span className="text-sm font-semibold truncate">{item.workflow || item.method || 'Advising turn'}</span>
                          <span className="text-[11px] text-muted-foreground whitespace-nowrap">{formatTime(item.created_at)}</span>
                        </div>
                        <p className="text-sm text-foreground line-clamp-3 mb-2">{item.query}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {item.method && (
                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                              {item.method}
                            </span>
                          )}
                          {item.quality_path && (
                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                              {item.quality_path}
                            </span>
                          )}
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                            {Math.round((item.confidence || 0) * 100)}% confidence
                          </span>
                          {evaluation && (
                            <span className={cn('text-[11px] px-2 py-0.5 rounded-full font-medium', getEvalBadgeClass(evaluation.status))}>
                              {evaluation.status.toUpperCase()} {formatPercent(evaluation.score)}
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="rounded-2xl border bg-card min-h-[520px]">
            {loadingDetail ? (
              <div className="flex items-center justify-center h-full min-h-[520px] text-muted-foreground text-sm gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading replay detail…
              </div>
            ) : !selectedReplay ? (
              <div className="flex items-center justify-center h-full min-h-[520px] text-muted-foreground text-sm">
                Select a replay to inspect the saved turn.
              </div>
            ) : (
              <div className="p-5 space-y-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">{selectedReplay.workflow || selectedReplay.method || 'Replay Detail'}</h2>
                    <p className="text-xs text-muted-foreground mt-1">{selectedReplay.id} • {formatTime(selectedReplay.created_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedReplay.method && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {selectedReplay.method}
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                      <Shield className="h-3 w-3" />
                      {Math.round((selectedReplay.confidence || 0) * 100)}% confidence
                    </span>
                    {selectedEvaluation && (
                      <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium', getEvalBadgeClass(selectedEvaluation.status))}>
                        {selectedEvaluation.status === 'pass' ? <CheckCircle2 className="h-3 w-3" /> : selectedEvaluation.status === 'fail' ? <XCircle className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                        Replay eval {formatPercent(selectedEvaluation.score)}
                      </span>
                    )}
                  </div>
                </div>

                {selectedEvaluation && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <div>
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Regression Evaluation</p>
                        <p className="text-sm text-muted-foreground">Lightweight checks over grounding, dependencies, blockers, and decision structure.</p>
                      </div>
                      <span className={cn('text-xs px-2 py-1 rounded-full font-medium', getEvalBadgeClass(selectedEvaluation.status))}>
                        {selectedEvaluation.status.toUpperCase()}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Score</p>
                        <p className="font-semibold">{formatPercent(selectedEvaluation.score)}</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Citations</p>
                        <p className="font-semibold">{selectedEvaluation.metrics?.citation_count ?? 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Trace Items</p>
                        <p className="font-semibold">{selectedEvaluation.metrics?.retrieval_trace_count ?? 0}</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                      <div>
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Checks</p>
                        <div className="space-y-2">
                          {Object.entries(selectedEvaluation.checks || {}).map(([key, passed]) => (
                            <div key={key} className="flex items-center justify-between rounded-lg border bg-card px-3 py-2 text-sm">
                              <span>{formatPriority(key)}</span>
                              <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium', passed ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300')}>
                                {passed ? 'Pass' : 'Fail'}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Issues</p>
                        {(selectedEvaluation.issues || []).length > 0 ? (
                          <div className="space-y-2">
                            {selectedEvaluation.issues.map((issue) => (
                              <div key={issue} className="rounded-lg border bg-card px-3 py-2 text-sm text-muted-foreground">
                                {issue}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-lg border bg-card px-3 py-2 text-sm text-green-700 dark:text-green-300">
                            No issues detected in the lightweight replay checks.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Query</p>
                    <p className="text-sm whitespace-pre-wrap">{selectedReplay.query}</p>
                  </div>
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Runtime Snapshot</p>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedReplay.runtime_snapshot?.selected_text_model && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-card border">
                          {selectedReplay.runtime_snapshot.selected_text_model}
                        </span>
                      )}
                      {selectedReplay.runtime_snapshot?.selected_retrieval_mode && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-card border">
                          {selectedReplay.runtime_snapshot.selected_retrieval_mode}
                        </span>
                      )}
                      {(selectedReplay.student_strategy?.priorities || []).map((priority) => (
                        <span key={priority} className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                          {formatPriority(priority)}
                        </span>
                      ))}
                      {selectedReplay.student_operating_model?.risk_tolerance && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {formatPriority(selectedReplay.student_operating_model.risk_tolerance)} risk
                        </span>
                      )}
                      {selectedReplay.student_operating_model?.certainty_preference && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Certainty: {formatPriority(selectedReplay.student_operating_model.certainty_preference)}
                        </span>
                      )}
                      {selectedReplay.session_memory?.transcript_digest?.kept_turns > 0 && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {selectedReplay.session_memory.transcript_digest.kept_turns} turns kept
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border bg-muted/20 p-4">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Answer</p>
                  <div className="text-sm whitespace-pre-wrap leading-relaxed max-h-[340px] overflow-y-auto scrollbar-fade">
                    {selectedReplay.answer || 'No answer content saved.'}
                  </div>
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Evidence Overview</p>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Documents</p>
                        <p className="font-semibold">{selectedReplay.evidence_overview?.document_count ?? 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Web</p>
                        <p className="font-semibold">{selectedReplay.evidence_overview?.web_count ?? 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Evidence Facts</p>
                        <p className="font-semibold">{selectedReplay.evidence_overview?.evidence_record_count ?? 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Profile Facts</p>
                        <p className="font-semibold">{selectedReplay.evidence_overview?.profile_fact_count ?? 0}</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Retrieval Summary</p>
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {selectedReplay.retrieval_summary?.strategy && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                          {selectedReplay.retrieval_summary.strategy}
                        </span>
                      )}
                      {Object.entries(selectedReplay.dependency_status || {}).map(([name, status]) => (
                        <span
                          key={name}
                          className={cn(
                            'text-xs px-2 py-0.5 rounded-full font-medium',
                            status === 'connected'
                              ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                              : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                          )}
                        >
                          {name}: {status}
                        </span>
                      ))}
                    </div>
                    <div className="space-y-2 max-h-[240px] overflow-y-auto scrollbar-fade">
                      {(selectedReplay.retrieval_trace || []).slice(0, 8).map((item, index) => (
                        <div key={`${item.source}-${item.label}-${index}`} className="rounded-lg border bg-card px-3 py-2 text-sm">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium truncate">{item.label}</span>
                            <span className="text-xs text-muted-foreground">{item.source}</span>
                          </div>
                          {item.reason?.matched_terms?.length > 0 && (
                            <p className="text-xs text-muted-foreground mt-1">
                              matched: {item.reason.matched_terms.slice(0, 5).join(', ')}
                            </p>
                          )}
                        </div>
                      ))}
                      {(!selectedReplay.retrieval_trace || selectedReplay.retrieval_trace.length === 0) && (
                        <p className="text-sm text-muted-foreground">No retrieval trace saved for this turn.</p>
                      )}
                    </div>
                  </div>
                </div>

                {selectedReplay.recommendation_outcome_profile?.follow_through_style && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Recommendation History</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {selectedReplay.recommendation_outcome_profile.follow_through_style.replace(/_/g, ' ')}
                      </span>
                      {(selectedReplay.recommendation_outcome_profile.preferred_recommendation_types || []).slice(0, 3).map((item) => (
                        <span key={item} className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Prefers {item}
                        </span>
                      ))}
                      {typeof selectedReplay.recommendation_outcome_profile.follow_through_ratio === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Follow-through {(selectedReplay.recommendation_outcome_profile.follow_through_ratio * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {selectedReplay.decision_continuity?.is_continuation && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Decision Continuity</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        Continuing prior plan
                      </span>
                      {selectedReplay.decision_continuity.latest_title && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {selectedReplay.decision_continuity.latest_title}
                        </span>
                      )}
                      {selectedReplay.decision_continuity.related_count > 1 && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {selectedReplay.decision_continuity.related_count} related decisions
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {selectedReplay.retrieval_diagnostics?.evidence_quality && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Evidence Quality</p>
                    <div className="grid grid-cols-2 xl:grid-cols-4 gap-2 text-sm">
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Overall</p>
                        <p className="font-semibold">{Math.round((selectedReplay.retrieval_diagnostics.evidence_quality.overall_quality || 0) * 100)}%</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Doc Trust</p>
                        <p className="font-semibold">{Math.round((selectedReplay.retrieval_diagnostics.evidence_quality.document_trust_avg || 0) * 100)}%</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Web Quality</p>
                        <p className="font-semibold">{Math.round((selectedReplay.retrieval_diagnostics.evidence_quality.web_quality_avg || 0) * 100)}%</p>
                      </div>
                      <div className="rounded-lg border bg-card px-3 py-2">
                        <p className="text-xs text-muted-foreground">Official Web Hits</p>
                        <p className="font-semibold">{selectedReplay.retrieval_diagnostics.evidence_quality.official_web_hits || 0}</p>
                      </div>
                    </div>
                  </div>
                )}

                {selectedReplay.citations?.length > 0 && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Sources</p>
                    <div className="space-y-2">
                      {selectedReplay.citations.map((citation, index) => (
                        <a
                          key={`${citation.source}-${index}`}
                          href={citation.source}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-primary hover:underline"
                        >
                          <ExternalLink className="h-3.5 w-3.5 flex-shrink-0" />
                          <span className="truncate">{citation.metadata?.title || citation.source}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                {selectedReplay.decision_payload?.recommendation_paths?.length > 0 && (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Recommendation Paths</p>
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                      {selectedReplay.decision_payload.recommendation_paths.map((path) => (
                        <div key={path.label} className="rounded-lg border bg-card px-3 py-3">
                          <div className="flex items-center gap-2 mb-2">
                            <Sparkles className="h-3.5 w-3.5 text-primary" />
                            <span className="text-sm font-semibold">{path.label}</span>
                          </div>
                          <p className="text-sm text-muted-foreground">{path.summary || path.rationale || 'No summary available.'}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="rounded-xl border bg-muted/20 p-4">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Trace Summary</p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                    <div className="rounded-lg border bg-card px-3 py-2">
                      <p className="text-xs text-muted-foreground">Stop Reason</p>
                      <p className="font-medium">{selectedReplay.stop_reason || 'n/a'}</p>
                    </div>
                    <div className="rounded-lg border bg-card px-3 py-2">
                      <p className="text-xs text-muted-foreground">Session</p>
                      <p className="font-medium truncate">{selectedReplay.session_id}</p>
                    </div>
                    <div className="rounded-lg border bg-card px-3 py-2">
                      <p className="text-xs text-muted-foreground">Saved</p>
                      <p className="font-medium inline-flex items-center gap-1">
                        <Clock3 className="h-3.5 w-3.5 text-muted-foreground" />
                        {formatTime(selectedReplay.created_at)}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
