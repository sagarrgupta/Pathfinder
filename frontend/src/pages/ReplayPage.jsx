import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import { getReplay, getReplays } from '@/services/api';
import { History, Loader2, RefreshCw, Wrench, Search, Bot, FileText, Paperclip } from 'lucide-react';

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
    <pre className="text-xs whitespace-pre-wrap break-words overflow-x-auto rounded-lg border bg-muted/20 p-3">
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
  const [error, setError] = useState('');
  const [showCurrentStudentOnly, setShowCurrentStudentOnly] = useState(true);

  const filteredReplays = useMemo(() => {
    if (!showCurrentStudentOnly || !state.activeStudentId) return replays;
    return replays.filter((item) => item.student_id === state.activeStudentId);
  }, [replays, showCurrentStudentOnly, state.activeStudentId]);

  useEffect(() => { void loadList(); }, []);

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
  }, [filteredReplays, replayFromQuery, selectedReplayId]);

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
    } catch (err) {
      setError(err.message || 'Failed to load replay artifact.');
    } finally {
      setLoadingDetail(false);
    }
  };

  const toolCalls = Array.isArray(selectedReplay?.tool_call_log) ? selectedReplay.tool_call_log : [];
  const citations = Array.isArray(selectedReplay?.citations) ? selectedReplay.citations : [];
  const documentExtractions = Array.isArray(selectedReplay?.document_extractions) ? selectedReplay.document_extractions : [];
  const documentIngestion = selectedReplay?.document_ingestion || {};
  const patchSummaries = Array.isArray(documentIngestion?.patch_summaries) ? documentIngestion.patch_summaries : [];

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="max-w-7xl mx-auto p-6 space-y-6 animate-fade-in">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center">
              <History className="h-7 w-7 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Replay Browser</h1>
              <p className="text-muted-foreground text-sm mt-0.5">
                Inspect the exact tool calls, inputs, outputs, and final answer for each saved turn.
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

        <div className="grid grid-cols-1 xl:grid-cols-[320px,1fr] gap-6">
          <section className="rounded-2xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-semibold">Saved Replays</p>
                <p className="text-xs text-muted-foreground">
                  {filteredReplays.length} artifact{filteredReplays.length === 1 ? '' : 's'}
                </p>
              </div>
            </div>

            {loadingList ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading replay artifacts...
              </div>
            ) : filteredReplays.length === 0 ? (
              <p className="text-sm text-muted-foreground">No replay artifacts found yet.</p>
            ) : (
              <div className="space-y-2">
                {filteredReplays.map((item) => {
                  const isActive = item.id === selectedReplayId;
                  return (
                    <button
                      key={item.id}
                      onClick={() => void loadDetail(item.id)}
                      className={`w-full text-left rounded-xl border p-3 transition-colors ${isActive ? 'border-primary bg-primary/5' : 'hover:bg-muted/30'}`}
                    >
                      <p className="text-sm font-medium line-clamp-2">{item.query}</p>
                      <div className="flex flex-wrap gap-2 mt-2 text-xs text-muted-foreground">
                        {item.selected_specialist ? (
                          <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                            {formatLabel(item.selected_specialist)}
                          </span>
                        ) : null}
                        <span>{formatTime(item.created_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section className="rounded-2xl border bg-card p-5">
            {loadingDetail ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading replay detail...
              </div>
            ) : !selectedReplay ? (
              <p className="text-sm text-muted-foreground">Select a replay to inspect the saved turn.</p>
            ) : (
              <div className="space-y-6">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="text-xl font-semibold">
                      {selectedReplay.selected_specialist ? `${formatLabel(selectedReplay.selected_specialist)} replay` : 'Replay detail'}
                    </h2>
                    <p className="text-xs text-muted-foreground mt-1">
                      {selectedReplay.id} • {formatTime(selectedReplay.created_at)}
                    </p>
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

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Search className="h-4 w-4 text-primary" />
                      <p className="font-medium">Query</p>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{selectedReplay.query}</p>
                  </div>
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Bot className="h-4 w-4 text-primary" />
                      <p className="font-medium">Final Answer</p>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">
                      {selectedReplay.answer || selectedReplay.specialist_output?.message || 'No answer content saved.'}
                    </p>
                  </div>
                </div>

                <div className="rounded-xl border bg-muted/20 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <p className="font-medium">Long Context Snapshot</p>
                  </div>
                  <JsonBlock value={selectedReplay.long_context_payload || {}} />
                </div>

                <div className="rounded-xl border bg-muted/20 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <p className="font-medium">Profile Schema</p>
                  </div>
                  <JsonBlock value={selectedReplay.profile_schema || {}} />
                </div>

                {documentExtractions.length > 0 ? (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Paperclip className="h-4 w-4 text-primary" />
                      <p className="font-medium">Extracted Document Text</p>
                      <span className="text-xs text-muted-foreground">
                        {documentExtractions.length} document{documentExtractions.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div className="space-y-4">
                      {documentExtractions.map((item, index) => (
                        <div key={item.document_id || `${item.filename}-${index}`} className="rounded-xl border bg-card p-4">
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
                          <pre className="text-xs whitespace-pre-wrap break-words overflow-x-auto rounded-lg border bg-muted/20 p-3">
                            {item.text_preview || 'No extracted text saved.'}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {patchSummaries.length > 0 ? (
                  <div className="rounded-xl border bg-muted/20 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Paperclip className="h-4 w-4 text-primary" />
                      <p className="font-medium">Document Ingestion Patch</p>
                      <span className="text-xs text-muted-foreground">
                        {documentIngestion.entity_count || 0} entities • {documentIngestion.relationship_count || 0} relationships
                      </span>
                    </div>
                    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-4 text-xs">
                      <div className="rounded-lg border bg-card p-3">
                        <p className="text-muted-foreground">Chunks</p>
                        <p className="text-lg font-semibold">{documentIngestion.chunk_count || 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card p-3">
                        <p className="text-muted-foreground">Entities</p>
                        <p className="text-lg font-semibold">{documentIngestion.entity_count || 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card p-3">
                        <p className="text-muted-foreground">Relationships</p>
                        <p className="text-lg font-semibold">{documentIngestion.relationship_count || 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card p-3">
                        <p className="text-muted-foreground">Support Records</p>
                        <p className="text-lg font-semibold">{documentIngestion.support_record_count || documentIngestion.candidate_fact_count || 0}</p>
                      </div>
                      <div className="rounded-lg border bg-card p-3">
                        <p className="text-muted-foreground">Schema Sections</p>
                        <p className="text-lg font-semibold">{documentIngestion.schema_section_count || 0}</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      {patchSummaries.map((item, index) => (
                        <div key={item.document_id || `${item.filename}-${index}`} className="rounded-xl border bg-card p-4 space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{item.filename || 'Uploaded document'}</span>
                            <span className="text-xs text-muted-foreground">
                              {item.entity_count || 0} entities • {item.relationship_count || 0} relationships
                            </span>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Agent Result</p>
                            <JsonBlock value={item.agent_result || {}} />
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Saved Items</p>
                            <JsonBlock value={item.saved_items || []} />
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Context Updates</p>
                            <JsonBlock value={item.context_updates || {}} />
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Ingestion Tool Calls</p>
                            <JsonBlock value={item.tool_calls || []} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-xl border bg-muted/20 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Wrench className="h-4 w-4 text-primary" />
                    <p className="font-medium">Tool Calls</p>
                    <span className="text-xs text-muted-foreground">
                      {toolCalls.length} call{toolCalls.length === 1 ? '' : 's'}
                    </span>
                  </div>
                  {toolCalls.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No tool calls were saved for this turn.</p>
                  ) : (
                    <div className="space-y-4">
                      {toolCalls.map((item, index) => (
                        <div key={item.call_id || `${item.tool}-${index}`} className="rounded-xl border bg-card p-4 space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{item.tool || 'Unknown tool'}</span>
                            <span className={`px-2 py-0.5 rounded-full text-xs ${item.status === 'ok' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'}`}>
                              {item.status || 'unknown'}
                            </span>
                            {item.call_id ? (
                              <span className="text-xs text-muted-foreground">call_id: {item.call_id}</span>
                            ) : null}
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Input From LLM</p>
                            <JsonBlock value={item.input || item.args || {}} />
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1">Tool Output</p>
                            <JsonBlock value={item.output || item.result_summary || {}} />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border bg-muted/20 p-4">
                  <p className="font-medium mb-2">Citations</p>
                  {citations.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No citations saved.</p>
                  ) : (
                    <div className="space-y-2">
                      {citations.map((citation, index) => (
                        <div key={`${citation.url || citation.title || 'citation'}-${index}`} className="rounded-lg border bg-card p-3">
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
