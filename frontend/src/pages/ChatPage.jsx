import React, { useRef, useState, useEffect } from 'react';
import { useApp } from '@/context/AppContext';
import { chatSSE, checkDocumentExists } from '@/services/api';
import MessageList from '@/components/chat/MessageList';
import InputArea from '@/components/chat/InputArea';
import {
  Sparkles, MessageSquare, BookOpen, Briefcase, FileText,
  GraduationCap, ArrowRight, AlertTriangle, Globe, Search,
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
  const { state, dispatch, createSession } = useApp();
  const [files, setFiles] = useState([]);
  const [isGlobalUpload, setIsGlobalUpload] = useState(false);
  const [replaceFlags, setReplaceFlags] = useState({});  // filename -> true if user chose to replace
  const abortRef = useRef(null);

  // Duplicate file dialog state
  const [dupDialog, setDupDialog] = useState({ open: false, filename: '', pendingFile: null });

  const sessionId = state.activeSessionId;
  const messages = state.messagesBySession[sessionId] || [];

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
    // Find files that were just added (not already in the existing list)
    const existingNames = new Set(files.map((f) => f.name));
    const justAdded = newFiles.filter((f) => !existingNames.has(f.name));

    // Check each newly added file for duplicates in the profile
    for (const file of justAdded) {
      try {
        const { exists } = await checkDocumentExists(file.name);
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

    // Add empty assistant message (will be streamed into)
    dispatch({
      type: 'ADD_MESSAGE',
      payload: {
        sessionId: sid,
        message: { role: 'assistant', content: '', metadata: {}, progress: [] },
      },
    });

    dispatch({ type: 'SET_STREAMING', payload: true });

    let tokenBuffer = '';

    abortRef.current = chatSSE(
      { query, sessionId: sid, files: pendingFiles, isGlobalUpload, replaceFilenames: pendingReplaceNames },
      {
        onProgress: (data) => {
          dispatch({
            type: 'APPEND_MESSAGE_PROGRESS',
            payload: { sessionId: sid, progress: data },
          });
        },
        onToken: (data) => {
          tokenBuffer += data.content;
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: { sessionId: sid, update: { content: tokenBuffer } },
          });
        },
        onDone: (data) => {
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: {
              sessionId: sid,
              update: {
                metadata: {
                  confidence: data.confidence,
                  citations: data.citations,
                  method: data.method,
                },
              },
            },
          });
          dispatch({ type: 'SET_STREAMING', payload: false });

          // Smart auto-title from first query
          const currentMessages = state.messagesBySession[sid] || [];
          if (currentMessages.length <= 1) {
            const title = generateSmartTitle(query);
            dispatch({
              type: 'SET_SESSIONS',
              payload: state.sessions.map((s) =>
                s.session_id === sid ? { ...s, title } : s
              ),
            });
          }
        },
        onError: (error) => {
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: { sessionId: sid, update: { content: `Error: ${error}` } },
          });
          dispatch({ type: 'SET_STREAMING', payload: false });
        },
      }
    );
  };

  const handleStop = () => {
    abortRef.current?.abort();
    dispatch({ type: 'SET_STREAMING', payload: false });
  };

  const handleSuggestionClick = (text) => {
    if (!sessionId) createSession();
    // Small delay for session to initialize
    setTimeout(() => handleSend(text), 50);
  };

  // ── Personalization ──
  const profile = state.profile;
  const studentName = profile?.personal?.name?.split(' ')[0] || '';
  const hasProfile = !!(profile?.skills?.length || profile?.courses?.length);

  // Build personalized suggestions based on profile
  const suggestions = React.useMemo(() => {
    if (!hasProfile) return DEFAULT_SUGGESTIONS;

    const custom = [];

    // Course suggestion based on their program
    const program = profile?.personal?.program;
    if (program) {
      custom.push({
        icon: BookOpen,
        text: `What courses should I take next for my ${program}?`,
        color: 'text-blue-500 dark:text-blue-400',
      });
    } else {
      custom.push(DEFAULT_SUGGESTIONS[0]);
    }

    // Career suggestion based on skills
    const skills = profile?.skills?.slice(0, 3)?.map(s => s.name).join(', ');
    if (skills) {
      custom.push({
        icon: Briefcase,
        text: `Find jobs matching my skills: ${skills}`,
        color: 'text-emerald-500 dark:text-emerald-400',
      });
    } else {
      custom.push(DEFAULT_SUGGESTIONS[1]);
    }

    // Interview prep
    custom.push(DEFAULT_SUGGESTIONS[2]);

    // Web research
    custom.push(DEFAULT_SUGGESTIONS[3]);

    return custom;
  }, [hasProfile, profile]);

  // Time-aware greeting
  const timeGreeting = React.useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }, []);

  // Welcome screen when no session is active
  if (!sessionId) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center max-w-2xl w-full animate-fade-in">
          {/* Logo */}
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10 mb-6">
            <GraduationCap className="h-8 w-8 text-primary" />
          </div>

          <h1 className="text-3xl font-bold tracking-tight mb-2">
            {studentName
              ? `${timeGreeting}, ${studentName}`
              : 'Welcome to Pathfinder'}
          </h1>
          <p className="text-muted-foreground text-lg mb-8 max-w-md mx-auto">
            {hasProfile
              ? 'Your personalized academic and career assistant is ready. What would you like to explore today?'
              : 'Your AI-powered academic and career guidance assistant. Upload your resume or transcript to get started!'}
          </p>

          {/* Profile status badge */}
          {hasProfile && (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-xs font-medium mb-6">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Profile loaded — {profile?.courses?.length || 0} courses, {profile?.skills?.length || 0} skills
            </div>
          )}

          {/* Suggestion cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg mx-auto mb-8">
            {suggestions.map((s, i) => (
              <button
                key={i}
                onClick={() => handleSuggestionClick(s.text)}
                className="group flex items-start gap-3 p-4 rounded-xl border bg-card hover:bg-accent/50 hover:border-primary/20 text-left transition-all duration-200 hover:shadow-sm"
              >
                <s.icon className={`h-5 w-5 mt-0.5 flex-shrink-0 ${s.color}`} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm leading-snug">{s.text}</span>
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity mt-0.5 flex-shrink-0" />
              </button>
            ))}
          </div>

          {/* Keyboard hint */}
          <p className="text-xs text-muted-foreground">
            Press{' '}
            <kbd className="px-1.5 py-0.5 rounded bg-muted border text-[10px] font-mono font-medium">
              ⌘N
            </kbd>
            {' '}to start a new chat
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
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
                  "{dupDialog.filename}" already exists in your profile. Would you like to replace it with the new version?
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
      <div className="flex-1 overflow-y-auto scrollbar-fade">
        <MessageList messages={messages} isStreaming={state.isStreaming} />
      </div>

      {/* Input Area */}
      <InputArea
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={state.isStreaming}
        files={files}
        onFilesChange={handleFilesChange}
        isGlobalUpload={isGlobalUpload}
        onGlobalUploadChange={setIsGlobalUpload}
      />
    </div>
  );
}
