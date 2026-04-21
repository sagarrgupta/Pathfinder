import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import {
  MessageSquare, User, Settings, Plus, Trash2,
  PanelLeftClose, PanelLeftOpen, GraduationCap,
  Pin, PinOff, Pencil, Check, X, Search,
  History, ChevronDown,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/shared/Toast';

const MIN_WIDTH = 220;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 256;
const COLLAPSED_WIDTH = 48;

export default function Sidebar({ open, onToggle }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { state, dispatch, createSession, switchStudent, createStudent } = useApp();
  const toast = useToast();
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const editRef = useRef(null);

  // ── Resizable width ──
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = localStorage.getItem('pathfinder_sidebar_width');
      return saved ? Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Number(saved))) : DEFAULT_WIDTH;
    } catch { return DEFAULT_WIDTH; }
  });
  const [isResizing, setIsResizing] = useState(false);

  // Persist width
  useEffect(() => {
    try { localStorage.setItem('pathfinder_sidebar_width', String(sidebarWidth)); } catch {}
  }, [sidebarWidth]);

  // ── Drag handlers ──
  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e) => {
      const newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, e.clientX));
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, [isResizing]);

  const navItems = [
    { path: '/chat', label: 'Ask Pathfinder', icon: MessageSquare },
    { path: '/student', label: 'Profile', icon: User },
    { path: '/replays', label: 'Saved Runs', icon: History },
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  const handleNewChat = () => {
    createSession();
    navigate('/chat');
  };

  const handleDeleteSession = (e, sessionId) => {
    e.stopPropagation();
    dispatch({ type: 'REMOVE_SESSION', payload: sessionId });
  };

  const handleStudentChange = async (e) => {
    const nextStudentId = e.target.value;
    try {
      await switchStudent(nextStudentId);
      navigate('/chat');
    } catch (err) {
      toast.error(`Failed to switch student: ${err.message}`);
    }
  };

  const handleCreateStudent = async () => {
    const name = window.prompt('Enter a name for the new student');
    if (!name?.trim()) return;
    try {
      await createStudent({ name: name.trim() });
      toast.success(`Created student ${name.trim()}`);
      navigate('/student');
    } catch (err) {
      toast.error(`Failed to create student: ${err.message}`);
    }
  };

  const handleSelectSession = (sessionId) => {
    if (editingId) return;
    dispatch({ type: 'SET_ACTIVE_SESSION', payload: sessionId });
    navigate('/chat');
  };

  // ── Rename handlers ──
  const startRename = (e, session) => {
    e.stopPropagation();
    setEditingId(session.session_id);
    setEditValue(session.title);
  };

  const confirmRename = (e) => {
    if (e) e.stopPropagation();
    const trimmed = editValue.trim();
    if (trimmed && editingId) {
      dispatch({ type: 'RENAME_SESSION', payload: { sessionId: editingId, title: trimmed } });
    }
    setEditingId(null);
    setEditValue('');
  };

  const cancelRename = (e) => {
    if (e) e.stopPropagation();
    setEditingId(null);
    setEditValue('');
  };

  const handleRenameKeyDown = (e) => {
    if (e.key === 'Enter') confirmRename(e);
    if (e.key === 'Escape') cancelRename(e);
  };

  useEffect(() => {
    if (editingId && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editingId]);

  // ── Pin handler ──
  const handleTogglePin = (e, sessionId) => {
    e.stopPropagation();
    dispatch({ type: 'TOGGLE_PIN_SESSION', payload: sessionId });
  };

  // ── Filtered & sorted sessions ──
  const currentStudentSessions = state.sessions.filter(
    (s) => s.student_id === state.activeStudentId
  );
  const filteredSessions = currentStudentSessions.filter((s) => {
    if (!searchQuery.trim()) return true;
    return s.title.toLowerCase().includes(searchQuery.toLowerCase());
  });
  const pinnedSessions = filteredSessions.filter((s) => s.pinned);
  const unpinnedSessions = filteredSessions.filter((s) => !s.pinned);

  const getStudentLabel = useCallback((studentId) => {
    const listStudent = state.students.find((student) => student.student_id === studentId);
    if (listStudent?.name?.trim()) return listStudent.name.trim();

    if (state.activeStudentId === studentId) {
      const activeName = state.student?.root_properties?.name || state.student?.name || '';
      if (String(activeName).trim()) return String(activeName).trim();
    }

    return studentId;
  }, [state.activeStudentId, state.student, state.students]);

  const renderSession = (session) => {
    const isEditing = editingId === session.session_id;
    const isActive = state.activeSessionId === session.session_id;

    return (
      <div
        key={session.session_id}
        onClick={() => handleSelectSession(session.session_id)}
        className={cn(
          'group/session flex w-full cursor-pointer items-center justify-between rounded-2xl border px-3 py-2.5 text-sm transition-all',
          isActive
            ? 'border-primary/25 bg-gradient-to-r from-primary/12 to-warning/10 text-foreground shadow-sm'
            : 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-accent/35'
        )}
      >
        {isEditing ? (
          <div className="flex items-center gap-1 flex-1 min-w-0" onClick={(e) => e.stopPropagation()}>
            <input
              ref={editRef}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={handleRenameKeyDown}
              onBlur={confirmRename}
              className="min-w-0 flex-1 rounded-xl border border-border bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              onClick={confirmRename}
              className="p-1 rounded-md hover:bg-green-100 hover:text-green-600 dark:hover:bg-green-900/30 dark:hover:text-green-400 transition-colors flex-shrink-0"
              title="Save"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={cancelRename}
              className="p-1 rounded-md hover:bg-red-100 hover:text-red-600 dark:hover:bg-red-900/30 dark:hover:text-red-400 transition-colors flex-shrink-0"
              title="Cancel"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 flex-1 min-w-0">
              {session.pinned && <Pin className="h-3 w-3 flex-shrink-0 text-primary" />}
              <div className="flex-1 min-w-0">
                <span className="block truncate text-left font-medium" title={session.title}>{session.title}</span>
              </div>
            </div>

            <div className="hidden group-hover/session:flex items-center gap-0.5 flex-shrink-0 ml-1">
              <button
                onClick={(e) => startRename(e, session)}
                className="p-1 rounded-md hover:bg-accent transition-colors"
                title="Rename chat"
              >
                <Pencil className="h-3 w-3" />
              </button>
              <button
                onClick={(e) => handleTogglePin(e, session.session_id)}
                className={cn(
                  'p-1 rounded-md transition-colors',
                  session.pinned
                    ? 'text-primary hover:bg-primary/10'
                    : 'hover:bg-accent'
                )}
                title={session.pinned ? 'Unpin chat' : 'Pin chat'}
              >
                {session.pinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
              </button>
              <button
                onClick={(e) => handleDeleteSession(e, session.session_id)}
                className="p-1 rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors"
                title="Delete chat"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </>
        )}
      </div>
    );
  };

  const currentWidth = open ? sidebarWidth : COLLAPSED_WIDTH;

  return (
    <aside
      className="relative flex flex-shrink-0 flex-col overflow-hidden rounded-[28px] border border-border/70 bg-card/80 shadow-[0_18px_60px_rgba(15,23,42,0.10)] backdrop-blur-xl"
      style={{
        width: currentWidth,
        minWidth: currentWidth,
        transition: isResizing ? 'none' : 'width 200ms ease-in-out, min-width 200ms ease-in-out',
      }}
    >
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.10),transparent_34%),linear-gradient(180deg,hsl(var(--card)/0.96),hsl(var(--card)/0.82))]" />
      {/* Header */}
      {open && (
        <div className="relative flex min-h-[84px] items-start justify-between border-b border-border/60 px-4 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-warning/15 ring-1 ring-primary/15">
              <GraduationCap className="h-5 w-5 text-primary" />
            </div>
            <div className="min-w-0">
              <h1 className="whitespace-nowrap text-base font-semibold tracking-tight leading-tight">Pathfinder</h1>
              {(state.student?.root_properties?.name || state.activeStudentId) && (
                <p className="mt-1 truncate text-[11px] text-muted-foreground leading-tight">
                  Working with {(state.student?.root_properties?.name || state.activeStudentId).split(' ')[0]}
                </p>
              )}
            </div>
          </div>
          <button onClick={onToggle} className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border border-border/60 bg-background/60 transition-colors hover:bg-accent" title="Collapse sidebar">
            <PanelLeftClose className="h-4.5 w-4.5 text-muted-foreground" />
          </button>
        </div>
      )}

      {/* New Chat Button (expanded) */}
      {open && (
        <div className="relative space-y-3 px-4 pb-2 pt-4 pr-5">
          <div className="hero-panel p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-[0.24em]">
                Current Profile
              </p>
              <button
                onClick={handleCreateStudent}
                className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-background/80 px-2.5 py-1 text-[11px] font-medium text-primary hover:bg-accent"
                title="Create student"
              >
                <Plus className="h-3 w-3" />
                New
              </button>
            </div>
            <div className="relative">
              <select
                value={state.activeStudentId}
                onChange={handleStudentChange}
                className="w-full appearance-none rounded-2xl border border-border/70 bg-card/92 px-4 py-3 pr-11 text-sm text-foreground shadow-sm outline-none [color-scheme:light] focus:ring-1 focus:ring-ring/50 dark:[color-scheme:dark]"
              >
                {state.students.length === 0 ? (
                  <option value={state.activeStudentId}>{getStudentLabel(state.activeStudentId)}</option>
                ) : (
                  state.students.map((student) => (
                    <option key={student.student_id} value={student.student_id}>
                      {getStudentLabel(student.student_id)}
                    </option>
                  ))
                )}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              This profile powers chat answers, document memory, and saved context.
            </p>
          </div>
          <button
            onClick={handleNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border border-primary/20 bg-gradient-to-r from-primary/14 to-warning/10 px-4 py-3.5 text-sm font-semibold text-foreground shadow-sm transition-all hover:border-primary/35 hover:shadow-[0_12px_30px_rgba(59,130,246,0.12)] active:scale-[0.98]"
          >
            <Plus className="h-4 w-4 flex-shrink-0" />
            <span className="whitespace-nowrap">New Chat</span>
          </button>
        </div>
      )}

      {/* Navigation */}
      <nav className={cn('relative space-y-1.5', open ? 'px-4 pt-3 pr-5' : 'px-1.5 pt-3')}>
        {/* Collapsed-only: Expand button */}
        {!open && (
          <button
            onClick={onToggle}
            className="flex h-11 w-full items-center justify-center rounded-2xl border border-border/60 bg-background/60 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="h-[1.15rem] w-[1.15rem]" />
          </button>
        )}
        {/* Collapsed-only: New Chat */}
        {!open && (
          <button
            onClick={handleNewChat}
            className="mt-1 flex h-11 w-full items-center justify-center rounded-2xl bg-primary/12 text-primary transition-colors hover:bg-primary/18"
            title="New chat"
          >
            <Plus className="h-5 w-5" />
          </button>
        )}
        {navItems.map(({ path, label, icon: Icon }) => (
          <button
            key={path}
            onClick={() => navigate(path)}
            className={cn(
              'w-full flex items-center gap-2 rounded-2xl text-sm transition-all',
              open ? 'px-3.5 py-2.5' : 'justify-center h-11',
              location.pathname === path
                ? 'bg-gradient-to-r from-primary/14 to-warning/10 text-foreground font-medium shadow-sm'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
            )}
            title={!open ? label : undefined}
          >
            <Icon className={cn('flex-shrink-0', open ? 'h-4 w-4' : 'h-[1.3rem] w-[1.3rem]')} />
            {open && <span className="whitespace-nowrap">{label}</span>}
          </button>
        ))}
      </nav>

      {/* Sessions List — only when expanded */}
      {open && (
        <div className="relative mt-4 flex-1 overflow-y-auto scrollbar-fade px-4 pb-4 pr-5">
          {/* Search bar */}
          {currentStudentSessions.length > 3 && (
            <div className="relative mb-3">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search chats…"
                className="w-full rounded-2xl border border-border/70 bg-background/80 py-2 pl-9 pr-3 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring/50"
              />
            </div>
          )}

          {pinnedSessions.length > 0 && (
            <>
              <p className="mb-2 flex items-center gap-1.5 px-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
                <Pin className="h-3 w-3" /> Pinned Chats
              </p>
              <div className="mb-4 space-y-1">
                {pinnedSessions.map(renderSession)}
              </div>
            </>
          )}

          <p className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
            Recent Conversations
          </p>
          {unpinnedSessions.length === 0 && pinnedSessions.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/70 bg-background/55 px-4 py-5 text-center text-xs text-muted-foreground/70">
              No conversations yet. Start a chat to build your Pathfinder history.
            </div>
          ) : unpinnedSessions.length === 0 ? null : (
            <div className="space-y-1">
              {unpinnedSessions.map(renderSession)}
            </div>
          )}
        </div>
      )}

      {/* ── Drag handle (right edge) ── */}
      {open && (
        <div
          onMouseDown={handleMouseDown}
          className={cn(
            'absolute top-0 right-0 z-10 h-full w-1.5 cursor-col-resize transition-colors',
            isResizing ? 'bg-primary/30' : 'hover:bg-primary/20'
          )}
        />
      )}
    </aside>
  );
}
