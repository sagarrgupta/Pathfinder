import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import {
  MessageSquare, User, Settings, Plus, Trash2,
  PanelLeftClose, PanelLeftOpen, GraduationCap,
  Pin, PinOff, Pencil, Check, X, Search,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const MIN_WIDTH = 220;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 256;
const COLLAPSED_WIDTH = 48;

export default function Sidebar({ open, onToggle }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { state, dispatch, createSession } = useApp();
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
  const sidebarRef = useRef(null);

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
    { path: '/chat', label: 'Chat', icon: MessageSquare },
    { path: '/profile', label: 'My Profile', icon: User },
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
  const filteredSessions = state.sessions.filter((s) => {
    if (!searchQuery.trim()) return true;
    return s.title.toLowerCase().includes(searchQuery.toLowerCase());
  });
  const pinnedSessions = filteredSessions.filter((s) => s.pinned);
  const unpinnedSessions = filteredSessions.filter((s) => !s.pinned);

  // ── Format relative time ──
  const formatRelativeTime = (dateStr) => {
    if (!dateStr) return '';
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

  const renderSession = (session) => {
    const isEditing = editingId === session.session_id;
    const isActive = state.activeSessionId === session.session_id;

    return (
      <div
        key={session.session_id}
        onClick={() => handleSelectSession(session.session_id)}
        className={cn(
          'w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-sm group/session transition-all cursor-pointer',
          isActive
            ? 'bg-accent text-accent-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-accent/50'
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
              className="flex-1 min-w-0 bg-background text-foreground text-sm px-2 py-1 rounded-md border border-border focus:outline-none focus:ring-1 focus:ring-primary"
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
              {session.pinned && <Pin className="h-3 w-3 text-primary flex-shrink-0" />}
              <div className="flex-1 min-w-0">
                <span className="truncate text-left block" title={session.title}>{session.title}</span>
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
    <div
      ref={sidebarRef}
      className="relative border-r bg-card/50 backdrop-blur-sm flex flex-col flex-shrink-0 overflow-hidden"
      style={{
        width: currentWidth,
        minWidth: currentWidth,
        transition: isResizing ? 'none' : 'width 200ms ease-in-out, min-width 200ms ease-in-out',
      }}
    >
      {/* Header */}
      {open && (
        <div className="p-3 border-b flex items-center justify-between min-h-[57px]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center ring-1 ring-primary/10">
              <GraduationCap className="h-4.5 w-4.5 text-primary" />
            </div>
            <div className="min-w-0">
              <h1 className="font-semibold text-base whitespace-nowrap tracking-tight leading-tight">Pathfinder</h1>
              {state.profile?.personal?.name && (
                <p className="text-[10px] text-muted-foreground truncate leading-tight">
                  {state.profile.personal.name.split(' ')[0]}'s Guide
                </p>
              )}
            </div>
          </div>
          <button onClick={onToggle} className="p-1.5 rounded-lg hover:bg-accent flex-shrink-0 transition-colors" title="Collapse sidebar">
            <PanelLeftClose className="h-4.5 w-4.5 text-muted-foreground" />
          </button>
        </div>
      )}

      {/* New Chat Button (expanded) */}
      {open && (
        <div className="p-3 pb-1">
          <button
            onClick={handleNewChat}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed border-border hover:bg-accent hover:border-primary/20 text-sm transition-all active:scale-[0.98]"
          >
            <Plus className="h-4 w-4 flex-shrink-0" />
            <span className="whitespace-nowrap font-medium">New Chat</span>
          </button>
        </div>
      )}

      {/* Navigation */}
      <nav className={cn('space-y-0.5', open ? 'px-3 pt-2' : 'px-1.5 pt-2')}>
        {/* Collapsed-only: Expand button */}
        {!open && (
          <button
            onClick={onToggle}
            className="w-full flex items-center justify-center p-2 rounded-lg hover:bg-accent text-muted-foreground hover:text-accent-foreground transition-colors"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}
        {/* Collapsed-only: New Chat */}
        {!open && (
          <button
            onClick={handleNewChat}
            className="w-full flex items-center justify-center p-2 rounded-lg hover:bg-accent text-muted-foreground hover:text-accent-foreground transition-colors"
            title="New chat"
          >
            <Plus className="h-4 w-4" />
          </button>
        )}
        {navItems.map(({ path, label, icon: Icon }) => (
          <button
            key={path}
            onClick={() => navigate(path)}
            className={cn(
              'w-full flex items-center gap-2 rounded-lg text-sm transition-all',
              open ? 'px-3 py-2' : 'justify-center p-2',
              location.pathname === path
                ? 'bg-accent text-accent-foreground font-medium shadow-sm'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
            )}
            title={!open ? label : undefined}
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            {open && <span className="whitespace-nowrap">{label}</span>}
          </button>
        ))}
      </nav>

      {/* Sessions List — only when expanded */}
      {open && (
        <div className="flex-1 overflow-y-auto scrollbar-fade mt-3 px-3">
          {/* Search bar */}
          {state.sessions.length > 3 && (
            <div className="relative mb-2">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search chats…"
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-ring/50"
              />
            </div>
          )}

          {pinnedSessions.length > 0 && (
            <>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest px-2.5 mb-1.5 flex items-center gap-1.5">
                <Pin className="h-3 w-3" /> Pinned
              </p>
              <div className="space-y-0.5 mb-3">
                {pinnedSessions.map(renderSession)}
              </div>
            </>
          )}

          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest px-2.5 mb-1.5">
            Recent Chats
          </p>
          {unpinnedSessions.length === 0 && pinnedSessions.length === 0 ? (
            <p className="text-xs text-muted-foreground/60 px-2.5 py-2">No chats yet. Start a new conversation!</p>
          ) : unpinnedSessions.length === 0 ? null : (
            <div className="space-y-0.5">
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
            'absolute top-0 right-0 w-1.5 h-full cursor-col-resize z-10 transition-colors',
            isResizing ? 'bg-primary/30' : 'hover:bg-primary/20'
          )}
        />
      )}
    </div>
  );
}
