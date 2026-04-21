import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import { getReplay, getReplays } from '@/services/api';
import { History, Loader2, RefreshCw, Wrench, Search, Bot, FileText, Paperclip, MessageSquare, ChevronDown, ChevronRight, Sparkles } from 'lucide-react';

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

function formatLabel(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function JsonBlock({ value }) {
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-border/60 bg-background/80 p-3.5 text-[11px] leading-5 text-muted-foreground shadow-sm">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function ReplayPage() {
  const { state } = useApp();
  const replayFromQuery = useReplayQueryParam();
  const [replays, setReplays] = useState([]);
  const [selectedReplayId, setSelectedReplayId] = useState('');
  const [selectedReplay, setSelectedReplay] = useState(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [pendingReplayId, setPendingReplayId] = useState('');
  const [error, setError] = useState('');
  const [showCurrentStudentOnly, setShowCurrentStudentOnly] = useState(true);
  const [expandedSessionId, setExpandedSessionId] = useState('');
  const [hasInitializedExpansion, setHasInitializedExpansion] = useState(false);
  const latestDetailRequestRef = useRef(0);

  const filteredReplays = useMemo(() => {
    if (!showCurrentStudentOnly || !state.activeStudentId) return replays;
    return replays.filter((item) => item.student_id === state.activeStudentId);
  }, [replays, showCurrentStudentOnly, state.activeStudentId]);

  const sessionLookup = useMemo(
    () => new Map(state.sessions.map((session) => [session.session_id, session])),
    [state.sessions]
  );

  const groupedReplays = useMemo(() => {
    const groups = new Map();
    filteredReplays.forEach((item) => {
      const sessionId = String(item.session_id || '').trim();
      if (!sessionId) return;
      const existing = groups.get(sessionId);
      if (existing) {
        existing.replays.push(item);
        if (String(item.created_at || '') > String(existing.latestCreatedAt || '')) {
          existing.latestCreatedAt = item.created_at || '';
        }
        return;
      }
      const session = sessionLookup.get(sessionId);
      groups.set(sessionId, {
        sessionId,
        title: session?.title || sessionId,
        latestCreatedAt: item.created_at || '',
        replays: [item],
      });
    });
    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        replays: [...group.replays].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))),
      }))
      .sort((a, b) => String(b.latestCreatedAt || '').localeCompare(String(a.latestCreatedAt || '')));
  }, [filteredReplays, sessionLookup]);

  useEffect(() => { void loadList(); }, []);

  useEffect(() => {
    if (replayFromQuery) {
      setSelectedReplayId(replayFromQuery);
      void loadDetail(replayFromQuery);
    }
  }, [replayFromQuery]);

  useEffect(() => {
    if (replayFromQuery) return;
    if (!selectedReplayId && groupedReplays.length > 0) {
      const nextId = groupedReplays[0].replays[0]?.id || '';
      if (!nextId) return;
      setSelectedReplayId(nextId);
      void loadDetail(nextId);
    }
  }, [groupedReplays, replayFromQuery, selectedReplayId]);

  useEffect(() => {
    if (groupedReplays.length === 0) {
      if (expandedSessionId) setExpandedSessionId('');
      if (hasInitializedExpansion) setHasInitializedExpansion(false);
      return;
    }
    if (groupedReplays.some((group) => group.sessionId === expandedSessionId)) {
      return;
    }
    if (hasInitializedExpansion && !expandedSessionId) {
      return;
    }
    const selectedGroup = groupedReplays.find((group) => group.replays.some((item) => item.id === selectedReplayId));
    setExpandedSessionId(selectedGroup?.sessionId || groupedReplays[0].sessionId);
    if (!hasInitializedExpansion) setHasInitializedExpansion(true);
  }, [expandedSessionId, groupedReplays, hasInitializedExpansion, selectedReplayId]);

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
    if (replayId === selectedReplayId && selectedReplay?.id === replayId) return;
    const requestId = latestDetailRequestRef.current + 1;
    latestDetailRequestRef.current = requestId;
    setSelectedReplayId(replayId);
    setPendingReplayId(replayId);
    setLoadingDetail(true);
    setError('');
    try {
      const data = await getReplay(replayId);
      if (latestDetailRequestRef.current !== requestId) return;
      setSelectedReplay(data);
    } catch (err) {
      if (latestDetailRequestRef.current !== requestId) return;
      setError(err.message || 'Failed to load replay artifact.');
    } finally {
      if (latestDetailRequestRef.current === requestId) {
        setLoadingDetail(false);
        setPendingReplayId('');
      }
    }
  };

  const toolCalls = Array.isArray(selectedReplay?.tool_call_log) ? selectedReplay.tool_call_log : [];
  const citations = Array.isArray(selectedReplay?.citations) ? selectedReplay.citations : [];
  const documentIngestion = selectedReplay?.document_ingestion || {};
  const ingestionDocuments = Array.isArray(documentIngestion?.documents) ? documentIngestion.documents : [];
  const queryIngestion = selectedReplay?.query_ingestion || {};
  const queryIngestionSummary =
    queryIngestion && typeof queryIngestion.model_summary === 'object' && queryIngestion.model_summary
      ? queryIngestion.model_summary
      : {};
  const queryIngestionToolCalls = Array.isArray(queryIngestion?.tool_call_log) ? queryIngestion.tool_call_log : [];
  const queryIngestionSavedItems = Array.isArray(queryIngestionSummary?.saved_items)
    ? queryIngestionSummary.saved_items
    : [];
  const queryIngestionStopReason = String(queryIngestionSummary?.stop_reason || '').trim();
  const queryIngestionGraphUpdates =
    queryIngestion && typeof queryIngestion.graph_updates === 'object' && queryIngestion.graph_updates
      ? queryIngestion.graph_updates
      : {};
  const queryIngestionGraphSchemaAfter =
    queryIngestion && typeof queryIngestion.graph_schema_after === 'object' && queryIngestion.graph_schema_after
      ? queryIngestion.graph_schema_after
      : {};
  const hasQueryIngestion =
    queryIngestionStopReason !== '' ||
    queryIngestionToolCalls.length > 0 ||
    queryIngestionSavedItems.length > 0 ||
    Object.keys(queryIngestionGraphUpdates).length > 0;
  const queryStopReasonStyle =
    queryIngestionStopReason === 'ingested'
      ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
      : queryIngestionStopReason === 'already_present'
        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
        : queryIngestionStopReason === 'no_useful_info'
          ? 'bg-muted text-muted-foreground'
          : 'bg-muted text-muted-foreground';

  const toggleSession = (sessionId) => {
    setHasInitializedExpansion(true);
    setExpandedSessionId((current) => (current === sessionId ? '' : sessionId));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto scrollbar-fade">
      <div className="mx-auto max-w-7xl space-y-6 p-6 animate-fade-in">
        <div className="hero-panel px-6 py-7 sm:px-8">
          <div className="mb-3 eyebrow">Saved runs</div>
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-[22px] bg-gradient-to-br from-primary/20 via-primary/10 to-warning/15 ring-1 ring-primary/15">
                <History className="h-7 w-7 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight">Saved Runs</h1>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Revisit past answers, uploaded documents, and the behind-the-scenes details from each saved turn.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Helpful for debugging, QA, and understanding why Pathfinder answered the way it did.
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
                onClick={() => void loadList()}
                className="soft-button rounded-lg px-3 py-2"
              >
                <RefreshCw className="h-4 w-4" />
                Refresh
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px,1fr]">
          <section className="section-card p-4 xl:sticky xl:top-6 xl:self-start">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-semibold">Chat Sessions</p>
                <p className="text-xs text-muted-foreground">
                  {groupedReplays.length} chat{groupedReplays.length === 1 ? '' : 's'} • {filteredReplays.length} saved repl{filteredReplays.length === 1 ? 'y' : 'ies'}
                </p>
              </div>
            </div>

            {loadingList ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading replay artifacts...
              </div>
            ) : groupedReplays.length === 0 ? (
              <p className="text-sm text-muted-foreground">No replay artifacts found yet.</p>
            ) : (
              <div className="space-y-2">
                {groupedReplays.map((group) => {
                  const isExpanded = expandedSessionId === group.sessionId;
                  const hasSelectedReplay = group.replays.some((item) => item.id === selectedReplayId);
                  return (
                    <div
                      key={group.sessionId}
                      className={`overflow-hidden rounded-2xl border transition-colors ${hasSelectedReplay ? 'border-primary/30 bg-primary/8 shadow-sm' : 'border-border/60 bg-card/40'}`}
                    >
                      <button
                        onClick={() => toggleSession(group.sessionId)}
                        className="flex w-full items-start justify-between gap-3 p-3 text-left hover:bg-muted/20"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <MessageSquare className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                            <p className="truncate text-sm font-medium">{group.title}</p>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                            <span>{group.replays.length} saved repl{group.replays.length === 1 ? 'y' : 'ies'}</span>
                            <span>{formatTime(group.latestCreatedAt)}</span>
                          </div>
                        </div>
                        {isExpanded ? (
                          <ChevronDown className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" />
                        )}
                      </button>

                      {isExpanded ? (
                        <div className="space-y-1 border-t border-border/60 bg-background/60 p-2">
                          {group.replays.map((item) => {
                            const isActive = item.id === selectedReplayId;
                            const isPending = item.id === pendingReplayId;
                            return (
                              <button
                                key={item.id}
                                onClick={() => void loadDetail(item.id)}
                                className={`w-full rounded-xl px-3 py-2.5 text-left transition-colors ${isActive ? 'bg-primary/12 text-foreground' : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'}`}
                              >
                                <p className="line-clamp-2 text-sm font-medium">{item.query}</p>
                                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                  {item.selected_specialist ? (
                                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">
                                      {formatLabel(item.selected_specialist)}
                                    </span>
                                  ) : null}
                                  <span>{formatTime(item.created_at)}</span>
                                  {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : null}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <section className="section-card">
            {loadingDetail && !selectedReplay ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading replay detail...
              </div>
            ) : !selectedReplay ? (
              <p className="text-sm text-muted-foreground">Select a replay to inspect the saved turn.</p>
            ) : (
              <div className="relative space-y-6">
                {loadingDetail ? (
                  <div className="pointer-events-none absolute right-0 top-0 inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow-sm backdrop-blur">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    Loading replay...
                  </div>
                ) : null}

                <div className="flex flex-col gap-3 pr-28 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="text-xl font-semibold">
                      {selectedReplay.selected_specialist ? `${formatLabel(selectedReplay.selected_specialist)} replay` : 'Replay detail'}
                    </h2>
                    <p className="text-xs text-muted-foreground mt-1">
                      {selectedReplay.id} • {formatTime(selectedReplay.created_at)}
                    </p>
                    {selectedReplay.session_id ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Chat session: <span className="font-mono text-[11px] text-foreground/90">{selectedReplay.session_id}</span>
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {selectedReplay.selected_specialist ? (
                      <span className="px-2.5 py-1 rounded-full bg-primary/10 text-primary">
                        {formatLabel(selectedReplay.selected_specialist)}
                      </span>
                    ) : null}
                    {selectedReplay.runtime_snapshot?.selected_text_model ? (
                      <span className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground">
                        {selectedReplay.runtime_snapshot.selected_text_model}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <div className="metric-tile">
                    <div className="flex items-center gap-2 mb-2">
                      <Search className="h-4 w-4 text-primary" />
                      <p className="font-medium">Query</p>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{selectedReplay.query}</p>
                  </div>
                  <div className="metric-tile">
                    <div className="flex items-center gap-2 mb-2">
                      <Bot className="h-4 w-4 text-primary" />
                      <p className="font-medium">Final Answer</p>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">
                      {selectedReplay.answer || selectedReplay.specialist_output?.message || 'No answer content saved.'}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <p className="font-medium">Session Context Used</p>
                    </div>
                    <JsonBlock value={selectedReplay.input_session_context || ''} />
                  </div>

                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <p className="font-medium">Longer Profile Memory Used</p>
                    </div>
                    <JsonBlock value={selectedReplay.input_long_context || ''} />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <p className="font-medium">Session Context Saved After The Turn</p>
                    </div>
                    <JsonBlock value={selectedReplay.session_context || ''} />
                  </div>

                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <p className="font-medium">Longer Profile Memory Saved After The Turn</p>
                    </div>
                    <JsonBlock value={selectedReplay.long_context || ''} />
                  </div>
                </div>

                <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <p className="font-medium">Profile Structure Snapshot</p>
                  </div>
                  <JsonBlock value={selectedReplay.student_schema || {}} />
                </div>

                {ingestionDocuments.length > 0 ? (
                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Paperclip className="h-4 w-4 text-primary" />
                      <p className="font-medium">Extracted Document Text</p>
                      <span className="text-xs text-muted-foreground">
                        {ingestionDocuments.length} document{ingestionDocuments.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div className="space-y-4">
                      {ingestionDocuments.map((item, index) => (
                        <div key={item.document_id || `${item.filename}-${index}`} className="rounded-2xl border border-border/70 bg-card p-4">
                          <div className="flex flex-wrap items-center gap-2 mb-2">
                            <span className="text-sm font-semibold">{item.filename || 'Uploaded document'}</span>
                            {item.role ? (
                              <span className="px-2 py-0.5 rounded-full text-xs bg-primary/10 text-primary">
                                {formatLabel(item.role)}
                              </span>
                            ) : null}
                            {item.page_count ? (
                              <span className="text-xs text-muted-foreground">
                                {item.page_count} page{item.page_count === 1 ? '' : 's'}
                              </span>
                            ) : null}
                          </div>
                          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-border/60 bg-background/80 p-3.5 text-[11px] leading-5 text-muted-foreground shadow-sm">
                            {item.text_preview || 'No extracted text saved.'}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {ingestionDocuments.length > 0 ? (
                  <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Paperclip className="h-4 w-4 text-primary" />
                      <p className="font-medium">Document Ingestion</p>
                    </div>
                    <div className="space-y-4">
                      {ingestionDocuments.map((item, index) => (
                        <div key={item.document_id || `${item.filename}-${index}`} className="rounded-2xl border border-border/70 bg-card p-4 space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{item.filename || 'Uploaded document'}</span>
                            <span className="text-xs text-muted-foreground">
                              {item.chunks_stored || 0} chunks stored
                            </span>
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Model Summary</p>
                            <JsonBlock value={item.ingestion_result?.model_summary || {}} />
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Graph Updates</p>
                            <JsonBlock value={item.ingestion_result?.graph_updates || {}} />
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Graph Schema After</p>
                            <JsonBlock value={item.ingestion_result?.graph_schema_after || {}} />
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Ingestion Tool Calls</p>
                            <JsonBlock value={item.ingestion_result?.tool_call_log || []} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {hasQueryIngestion ? (
                  <div className="rounded-[22px] border border-primary/30 bg-primary/5 p-4">
                    <div className="flex flex-wrap items-center gap-2 mb-3">
                      <Sparkles className="h-4 w-4 text-primary" />
                      <p className="font-medium">Chat-Message Ingestion</p>
                      <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                        opportunistic
                      </span>
                      {queryIngestionStopReason ? (
                        <span className={`px-2 py-0.5 rounded-full text-xs ${queryStopReasonStyle}`}>
                          {formatLabel(queryIngestionStopReason)}
                        </span>
                      ) : null}
                      <span className="text-xs text-muted-foreground">
                        {queryIngestionToolCalls.length} tool call{queryIngestionToolCalls.length === 1 ? '' : 's'}
                      </span>
                      {queryIngestionSavedItems.length > 0 ? (
                        <span className="text-xs text-muted-foreground">
                          {queryIngestionSavedItems.length} saved item{queryIngestionSavedItems.length === 1 ? '' : 's'}
                        </span>
                      ) : null}
                    </div>

                    {queryIngestionSummary?.summary ? (
                      <p className="mb-3 text-sm text-muted-foreground">
                        {queryIngestionSummary.summary}
                      </p>
                    ) : null}

                    {queryIngestionSavedItems.length > 0 ? (
                      <div className="mb-3 space-y-1.5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Saved Items</p>
                        <ul className="list-disc list-inside text-sm text-foreground/90 space-y-1">
                          {queryIngestionSavedItems.map((item, index) => (
                            <li key={`${item}-${index}`}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    <div className="space-y-3">
                      <div className="space-y-1.5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Model Summary</p>
                        <JsonBlock value={queryIngestionSummary} />
                      </div>
                      <div className="space-y-1.5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Graph Updates</p>
                        <JsonBlock value={queryIngestionGraphUpdates} />
                      </div>
                      <div className="space-y-1.5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Graph Schema After</p>
                        <JsonBlock value={queryIngestionGraphSchemaAfter} />
                      </div>
                      {queryIngestionToolCalls.length > 0 ? (
                        <div className="space-y-1.5">
                          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Ingestion Tool Calls</p>
                          <div className="space-y-3">
                            {queryIngestionToolCalls.map((item, index) => (
                              <div key={item.call_id || `${item.tool}-${index}`} className="rounded-2xl border border-border/70 bg-card p-4 space-y-3">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-sm font-semibold">{item.tool || 'Unknown tool'}</span>
                                  <span className={`px-2 py-0.5 rounded-full text-xs ${item.status === 'ok' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'}`}>
                                    {item.status || 'unknown'}
                                  </span>
                                  {item.call_id ? (
                                    <span className="text-xs text-muted-foreground">call_id: {item.call_id}</span>
                                  ) : null}
                                </div>
                                <div className="space-y-1.5">
                                  <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Input From LLM</p>
                                  <JsonBlock value={item.input || item.args || {}} />
                                </div>
                                <div className="space-y-1.5">
                                  <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Tool Output</p>
                                  <JsonBlock value={item.output || item.result_summary || {}} />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Wrench className="h-4 w-4 text-primary" />
                    <p className="font-medium">Specialist Tool Calls</p>
                    <span className="text-xs text-muted-foreground">
                      {toolCalls.length} call{toolCalls.length === 1 ? '' : 's'}
                    </span>
                  </div>
                  {toolCalls.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No tool calls were saved for this turn.</p>
                  ) : (
                    <div className="space-y-4">
                      {toolCalls.map((item, index) => (
                        <div key={item.call_id || `${item.tool}-${index}`} className="rounded-2xl border border-border/70 bg-card p-4 space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{item.tool || 'Unknown tool'}</span>
                            <span className={`px-2 py-0.5 rounded-full text-xs ${item.status === 'ok' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'}`}>
                              {item.status || 'unknown'}
                            </span>
                            {item.call_id ? (
                              <span className="text-xs text-muted-foreground">call_id: {item.call_id}</span>
                            ) : null}
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Input From LLM</p>
                            <JsonBlock value={item.input || item.args || {}} />
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Tool Output</p>
                            <JsonBlock value={item.output || item.result_summary || {}} />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-[22px] border border-border/70 bg-muted/20 p-4">
                  <p className="mb-2 font-medium">Citations</p>
                  {citations.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No citations saved.</p>
                  ) : (
                    <div className="space-y-2">
                      {citations.map((citation, index) => (
                        <div key={`${citation.url || citation.title || 'citation'}-${index}`} className="rounded-2xl border border-border/70 bg-card p-3.5 shadow-sm">
                          <p className="text-sm font-medium">{citation.title || citation.metadata?.title || `Source ${index + 1}`}</p>
                          <p className="text-xs text-muted-foreground break-all mt-1">{citation.url || citation.source || ''}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
