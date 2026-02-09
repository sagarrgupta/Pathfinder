import React, { useRef, useState, useEffect } from 'react';
import { useApp } from '@/context/AppContext';
import { chatSSE } from '@/services/api';
import MessageList from '@/components/chat/MessageList';
import InputArea from '@/components/chat/InputArea';
import {
  Sparkles, MessageSquare, BookOpen, Briefcase, FileText,
  GraduationCap, ArrowRight,
} from 'lucide-react';

const SUGGESTIONS = [
  { icon: BookOpen, text: 'What courses should I take for AI/ML?', color: 'text-blue-500 dark:text-blue-400' },
  { icon: Briefcase, text: 'Help me plan my career path', color: 'text-emerald-500 dark:text-emerald-400' },
  { icon: MessageSquare, text: 'Prepare me for a technical interview', color: 'text-purple-500 dark:text-purple-400' },
  { icon: FileText, text: 'Analyze my uploaded transcript', color: 'text-orange-500 dark:text-orange-400' },
];

export default function ChatPage() {
  const { state, dispatch, createSession } = useApp();
  const [files, setFiles] = useState([]);
  const [isGlobalUpload, setIsGlobalUpload] = useState(false);
  const abortRef = useRef(null);

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

  const handleSend = (query) => {
    if (!query.trim() || state.isStreaming) return;

    let sid = sessionId;
    if (!sid) {
      sid = createSession();
    }

    // Add user message
    dispatch({
      type: 'ADD_MESSAGE',
      payload: { sessionId: sid, message: { role: 'user', content: query } },
    });

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
      { query, sessionId: sid, files, isGlobalUpload },
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
          setFiles([]);

          // Update session title from first query
          const currentMessages = state.messagesBySession[sid] || [];
          if (currentMessages.length <= 1) {
            const title = query.length > 100 ? query.slice(0, 100) + '…' : query;
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
            Welcome to Pathfinder
          </h1>
          <p className="text-muted-foreground text-lg mb-8 max-w-md mx-auto">
            Your AI-powered academic and career guidance assistant.
            Ask anything about courses, careers, or interview prep.
          </p>

          {/* Suggestion cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg mx-auto mb-8">
            {SUGGESTIONS.map((s, i) => (
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
        onFilesChange={setFiles}
        isGlobalUpload={isGlobalUpload}
        onGlobalUploadChange={setIsGlobalUpload}
      />
    </div>
  );
}
