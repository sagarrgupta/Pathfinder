import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '@/context/AppContext';
import { useToast } from '@/components/shared/Toast';
import { chatSSE, checkDocumentExists } from '@/services/api';
import MessageList from '@/components/chat/MessageList';
import InputArea from '@/components/chat/InputArea';
import {
  MessageSquare, BookOpen, Briefcase,
  GraduationCap, ArrowRight, AlertTriangle, Globe,
} from 'lucide-react';

const DEFAULT_SUGGESTIONS = [
  { icon: BookOpen, text: 'What courses should I take next semester?', color: 'text-blue-500 dark:text-blue-400' },
  { icon: Briefcase, text: 'Find job openings based on my resume', color: 'text-emerald-500 dark:text-emerald-400' },
  { icon: MessageSquare, text: 'Prepare me for a technical interview', color: 'text-purple-500 dark:text-purple-400' },
  { icon: Globe, text: 'Summarize reviews from a university page', color: 'text-orange-500 dark:text-orange-400' },
];

/**
 * Generate a concise, readable title from the user's first query.
 * Strips filler words and URLs, capitalizes, and truncates.
 */
function generateSmartTitle(query) {
  // Remove URLs
  let clean = query.replace(/https?:\/\/[^\s]+/g, '').trim();

  // Remove common filler starts
  const fillers = [
    /^(hey |hi |hello |please |can you |could you |i want to |i need |help me )/i,
    /^(what |how |tell me |show me |find |search |summarize )/i,
  ];
  for (const filler of fillers) {
    clean = clean.replace(filler, '');
  }

  // Capitalize first letter
  clean = clean.charAt(0).toUpperCase() + clean.slice(1);

  // Truncate intelligently at word boundary
  if (clean.length > 60) {
    clean = clean.slice(0, 57).replace(/\s+\S*$/, '') + '…';
  }

  return clean || query.slice(0, 60);
}

export default function ChatPage() {
  const { state, dispatch, createSession, refreshStudent } = useApp();
  const toast = useToast();
  const [files, setFiles] = useState([]);
  const [replaceFlags, setReplaceFlags] = useState({});  // filename -> true if user chose to replace
  const abortRef = useRef(null);
  const requestTimingRef = useRef(null);
  const streamBufferRef = useRef({ sessionId: '', content: '', pendingContent: '', frameId: 0 });

  // Duplicate file dialog state
  const [dupDialog, setDupDialog] = useState({ open: false, filename: '', pendingFile: null });

  const sessionId = state.activeSessionId;
  const messages = state.messagesBySession[sessionId] || [];

  const flushStreamBuffer = (targetSessionId) => {
    const stream = streamBufferRef.current;
    if (stream.frameId) {
      cancelAnimationFrame(stream.frameId);
      stream.frameId = 0;
    }
    if (!targetSessionId || stream.sessionId !== targetSessionId || !stream.pendingContent) {
      return;
    }
    stream.content += stream.pendingContent;
    stream.pendingContent = '';
    dispatch({
      type: 'UPDATE_LAST_MESSAGE',
      payload: { sessionId: targetSessionId, update: { content: stream.content } },
    });
  };

  useEffect(() => () => {
    if (streamBufferRef.current.frameId) {
      cancelAnimationFrame(streamBufferRef.current.frameId);
    }
  }, []);

  // Keyboard shortcut: Cmd/Ctrl + N for new chat
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        createSession();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [createSession]);

  const handleFilesChange = async (newFiles) => {
    if (!state.activeStudentId) {
      toast.error('Create or select a student profile first.');
      return;
    }
    // Find files that were just added (not already in the existing list)
    const existingNames = new Set(files.map((f) => f.name));
    const justAdded = newFiles.filter((f) => !existingNames.has(f.name));

    // Check each newly added file for duplicates for the active student
    for (const file of justAdded) {
      try {
        const { exists } = await checkDocumentExists(file.name, state.activeStudentId);
        if (exists) {
          setDupDialog({ open: true, filename: file.name, pendingFile: file });
          // Remove this file from the list until user decides
          const filtered = newFiles.filter((f) => f !== file);
          setFiles(filtered);
          return;
        }
      } catch {
        // If check fails, proceed silently
      }
    }
    setFiles(newFiles);
  };

  const handleDupReplace = () => {
    const { pendingFile } = dupDialog;
    setDupDialog({ open: false, filename: '', pendingFile: null });
    setReplaceFlags((prev) => ({ ...prev, [pendingFile.name]: true }));
    setFiles((prev) => [...prev, pendingFile]);
  };

  const handleDupCancel = () => {
    setDupDialog({ open: false, filename: '', pendingFile: null });
  };

  const handleSend = (query) => {
    if (!query.trim() || state.isStreaming) return;
    if (!state.activeStudentId) {
      toast.error('Create or select a student profile first.');
      return;
    }

    let sid = sessionId;
    if (!sid) {
      sid = createSession();
    }

    // Capture files and replace flags before clearing
    const pendingFiles = [...files];
    const pendingReplaceNames = Object.keys(replaceFlags).filter((name) =>
      pendingFiles.some((f) => f.name === name)
    );

    // Add user message with attached file names so they appear in chat history
    const userMessage = {
      role: 'user',
      content: query,
      ...(pendingFiles.length > 0 && {
        attachments: pendingFiles.map((f) => ({ name: f.name, type: f.type, size: f.size })),
      }),
    };
    dispatch({
      type: 'ADD_MESSAGE',
      payload: { sessionId: sid, message: userMessage },
    });

    // Clear files and replace flags from input area immediately (like ChatGPT)
    setFiles([]);
    setReplaceFlags({});

    const request = { sessionId: sid, startedAt: Date.now(), clockStart: performance.now(), finished: false };
    requestTimingRef.current = request;
    const finishTiming = (status) => {
      request.finished = true;
      return { startedAt: request.startedAt, elapsedMs: Math.max(0, performance.now() - request.clockStart), status };
    };

    // Add empty assistant message (will be streamed into)
    dispatch({
      type: 'ADD_MESSAGE',
      payload: {
        sessionId: sid,
        message: { role: 'assistant', content: '', metadata: {}, progress: [], timing: { startedAt: request.startedAt } },
      },
    });

    dispatch({ type: 'SET_STREAMING', payload: true, sessionId: sid });
    streamBufferRef.current = { sessionId: sid, content: '', pendingContent: '', frameId: 0 };

    abortRef.current = chatSSE(
      {
        query,
        sessionId: sid,
        studentId: state.activeStudentId,
        files: pendingFiles,
        replaceFilenames: pendingReplaceNames,
        reasoning: state.settings.reasoning || 'medium',
      },
      {
        onProgress: (data) => {
          if (request.finished) return;
          dispatch({
            type: 'APPEND_MESSAGE_PROGRESS',
            payload: { sessionId: sid, progress: data },
          });
        },
        onToken: (data) => {
          if (request.finished) return;
          const stream = streamBufferRef.current;
          stream.sessionId = sid;
          stream.pendingContent += data.content;
          if (!stream.frameId) {
            stream.frameId = requestAnimationFrame(() => {
              stream.frameId = 0;
              flushStreamBuffer(sid);
            });
          }
        },
        onDone: (data) => {
          if (request.finished) return;
          const timing = finishTiming('completed');
          flushStreamBuffer(sid);
          const runtimeSnapshot = data.runtime_snapshot || {};
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: {
              sessionId: sid,
              update: {
                timing,
                metadata: {
                  citations: data.citations,
                  method: data.method,
                  replayId: data.replay_id,
                  dependencyStatus: data.dependency_status,
                  stopReason: data.stop_reason,
                  runtimeSnapshot: data.runtime_snapshot,
                  selectedSpecialist: data.selected_specialist,
                  routingScores: data.routing_scores,
                  routingReason: data.routing_reason,
                  toolCallLog: data.tool_call_log,
                  documentIngestion: data.document_ingestion || {},
                  specialistOutput: data.specialist_output,
                  reasoning: runtimeSnapshot.reasoning || state.settings.reasoning || 'medium',
                },
              },
            },
          });
          dispatch({ type: 'SET_STREAMING', payload: false });

          if (state.activeStudentId) {
            refreshStudent(state.activeStudentId).catch(() => {
            });
          }

          // Smart auto-title from first query
          const currentMessages = state.messagesBySession[sid] || [];
          if (currentMessages.length <= 1) {
            const title = generateSmartTitle(query);
            dispatch({
              type: 'RENAME_SESSION',
              payload: { sessionId: sid, title },
            });
          }
        },
        onError: (error) => {
          if (request.finished) return;
          const timing = finishTiming('error');
          flushStreamBuffer(sid);
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: { sessionId: sid, update: { content: `Error: ${error}`, timing } },
          });
          dispatch({ type: 'SET_STREAMING', payload: false });
        },
      }
    );
  };

  const handleStop = () => {
    const request = requestTimingRef.current;
    if (request && !request.finished) {
      request.finished = true;
      dispatch({
        type: 'UPDATE_LAST_MESSAGE',
        payload: {
          sessionId: request.sessionId,
          update: { timing: { startedAt: request.startedAt, elapsedMs: Math.max(0, performance.now() - request.clockStart), status: 'stopped' } },
        },
      });
    }
    flushStreamBuffer(streamBufferRef.current.sessionId);
    abortRef.current?.abort();
    dispatch({ type: 'SET_STREAMING', payload: false });
  };

  const handleSuggestionClick = (text) => {
    handleSend(text);
  };

  // ── Student context ──
  const student = state.student;
  const studentName = (student?.root_properties?.name || '').split(' ')[0] || '';
  const studentSections = Array.isArray(student?.sections) ? student.sections : [];
  const studentEntityTotal = Object.values(student?.section_items || {}).reduce(
    (sum, items) => sum + (Array.isArray(items) ? items.length : 0),
    0,
  );
  const hasStudentContext = studentSections.length > 0 || studentEntityTotal > 0;
  const suggestions = DEFAULT_SUGGESTIONS;
  // Time-aware greeting
  const timeGreeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }, []);

  // Welcome screen when no session is active
  if (!sessionId) {
    return (
      <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto scrollbar-fade px-6 py-8">
          <div className="flex min-h-full items-center justify-center">
            <div className="hero-panel w-full max-w-5xl animate-fade-in px-8 py-8 sm:px-10 sm:py-10">
              <div className="grid gap-8 lg:grid-cols-[1.25fr,0.95fr] lg:items-center">
                <div className="text-center lg:text-left">
                  <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-[24px] bg-gradient-to-br from-primary/20 via-primary/10 to-warning/15 ring-1 ring-primary/15">
                    <GraduationCap className="h-7 w-7 text-primary" />
                  </div>

                  <div className="eyebrow mb-4">Student graph + retrieval workspace</div>
                  <div className="eyebrow mb-4 ml-2 hidden sm:inline-flex">Built for grounded academic and career help</div>

                  <h1 className="mb-3 text-3xl font-bold tracking-tight sm:text-4xl">
                    {studentName
                      ? `${timeGreeting}, ${studentName}`
                      : 'Welcome to Pathfinder'}
                  </h1>
                  <p className="max-w-2xl text-balance text-base leading-7 text-muted-foreground lg:text-lg">
                    {hasStudentContext
                      ? 'Your workspace is ready with profile memory, structured student data, and document retrieval. Ask for plans, summaries, comparisons, or grounded recommendations.'
                      : 'Start with a transcript, resume, or other supporting document. Pathfinder will turn it into reusable context for future academic and career guidance.'}
                  </p>

                  {hasStudentContext && (
                    <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-4 py-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                      <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                      Profile ready: {studentSections.length} sections, {studentEntityTotal} saved items
                    </div>
                  )}

                  <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="metric-tile text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Memory</p>
                      <p className="mt-2 text-2xl font-semibold">{studentSections.length}</p>
                      <p className="mt-1 text-sm text-muted-foreground">profile sections ready to use</p>
                    </div>
                    <div className="metric-tile text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Saved Items</p>
                      <p className="mt-2 text-2xl font-semibold">{studentEntityTotal}</p>
                      <p className="mt-1 text-sm text-muted-foreground">facts Pathfinder can ground answers in</p>
                    </div>
                    <div className="metric-tile text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">Mode</p>
                      <p className="mt-2 text-2xl font-semibold">{(state.settings.reasoning || 'medium').toUpperCase()}</p>
                      <p className="mt-1 text-sm text-muted-foreground">current reasoning depth</p>
                    </div>
                  </div>
                </div>

                <div className="rounded-[24px] border border-border/70 bg-background/65 p-5 shadow-sm">
                  <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
                    Try a prompt
                  </p>
                  <div className="grid gap-3">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(s.text)}
                        className="group flex items-start gap-3 rounded-2xl border border-border/70 bg-card/72 p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/25 hover:bg-accent/35 hover:shadow-[0_18px_45px_rgba(15,23,42,0.08)]"
                      >
                        <s.icon className={`mt-0.5 h-5 w-5 flex-shrink-0 ${s.color}`} />
                        <div className="min-w-0 flex-1">
                          <span className="text-sm font-medium leading-snug">{s.text}</span>
                          <p className="mt-1 text-xs text-muted-foreground">Start a focused conversation with grounded context</p>
                        </div>
                        <ArrowRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </button>
                    ))}
                  </div>
                  <p className="mt-4 text-xs text-muted-foreground">
                    Press{' '}
                    <kbd className="rounded border bg-muted px-1.5 py-0.5 text-[10px] font-mono font-medium">
                      ⌘N
                    </kbd>
                    {' '}to start a new chat
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <InputArea
          onSend={handleSend}
          onStop={handleStop}
          isStreaming={state.isStreaming}
          files={files}
          onFilesChange={handleFilesChange}
          reasoning={state.settings.reasoning || 'medium'}
          onReasoningChange={(value) => dispatch({ type: 'SET_SETTINGS', payload: { reasoning: value } })}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      {/* Duplicate file dialog */}
      {dupDialog.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={handleDupCancel} />
          <div className="relative bg-card border rounded-2xl shadow-xl p-6 max-w-sm w-full mx-4 animate-fade-in-up">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h3 className="text-sm font-semibold">Duplicate Document</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  "{dupDialog.filename}" already exists for this student. Would you like to replace it with the new version?
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={handleDupCancel}
                className="px-4 py-2 text-sm font-medium rounded-lg border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDupReplace}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
              >
                Replace
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-fade px-3 pb-3 pt-5 md:px-5">
        <MessageList messages={messages} isStreaming={state.isStreaming} />
      </div>

      {/* Input Area */}
      <InputArea
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={state.isStreaming}
        files={files}
        onFilesChange={handleFilesChange}
        reasoning={state.settings.reasoning || 'medium'}
        onReasoningChange={(value) => dispatch({ type: 'SET_SETTINGS', payload: { reasoning: value } })}
      />
    </div>
  );
}
