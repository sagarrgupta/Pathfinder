import React, { createContext, useContext, useReducer, useCallback, useEffect, useRef } from 'react';
import { createProfile as createProfileRequest, getProfile, getProfiles } from '@/services/api';

const AppContext = createContext(null);

// ── LocalStorage helpers ────────────────────────────────────────

const STORAGE_KEY = 'pathfinder_state';
const RUNTIME_STUDENT_KEY = 'pathfinder_runtime_student_id';

function generateRuntimeStudentId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `student_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
  }
  return `student_${Math.random().toString(16).slice(2, 14)}`;
}

function getOrCreateRuntimeStudentId() {
  try {
    const saved = localStorage.getItem(RUNTIME_STUDENT_KEY);
    if (saved) return saved;
    const created = generateRuntimeStudentId();
    localStorage.setItem(RUNTIME_STUDENT_KEY, created);
    return created;
  } catch {
    return generateRuntimeStudentId();
  }
}

function loadPersistedState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      return {
        profiles: saved.profiles || [],
        activeStudentId: saved.activeStudentId || null,
        sessions: saved.sessions || [],
        activeSessionId: saved.activeSessionId || null,
        messagesBySession: saved.messagesBySession || {},
        settings: saved.settings || { topic_guard_enabled: true, reasoning: 'medium' },
        theme: saved.theme || 'system',
      };
    }
  } catch {
    // Corrupt data — ignore
  }
  return null;
}

function persistState(state) {
  try {
    const toSave = {
      profiles: state.profiles,
      activeStudentId: state.activeStudentId,
      sessions: state.sessions,
      activeSessionId: state.activeSessionId,
      messagesBySession: state.messagesBySession,
      settings: state.settings,
      theme: state.theme,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
  } catch {
    // Storage full or unavailable — ignore
  }
}

function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  const resolved = theme === 'system' ? getSystemTheme() : theme;
  document.documentElement.classList.toggle('dark', resolved === 'dark');
}

// ── State Shape ─────────────────────────────────────────────────

const persisted = loadPersistedState();

const initialState = {
  profiles: persisted?.profiles || [],
  activeStudentId: persisted?.activeStudentId || getOrCreateRuntimeStudentId(),
  // Sessions (restored from localStorage if available)
  sessions: persisted?.sessions || [],
  activeSessionId: persisted?.activeSessionId || null,

  // Messages per session: { [sessionId]: [{role, content, metadata}] }
  messagesBySession: persisted?.messagesBySession || {},

  // Profile
  profile: null,
  profileLoading: false,

  // Settings
  settings: persisted?.settings || { topic_guard_enabled: true, reasoning: 'medium' },

  // Theme
  theme: persisted?.theme || 'system',

  // UI (never persisted)
  sidebarOpen: true,
  isStreaming: false,
  streamProgress: [],
};

// ── Reducer ─────────────────────────────────────────────────────

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_PROFILES':
      return { ...state, profiles: action.payload };

    case 'SET_SESSIONS':
      return { ...state, sessions: action.payload };

    case 'SET_ACTIVE_STUDENT': {
      const nextStudentId = action.payload;
      const nextSessions = state.sessions.filter((s) => s.student_id === nextStudentId);
      return {
        ...state,
        activeStudentId: nextStudentId,
        activeSessionId: nextSessions[0]?.session_id || null,
        streamProgress: [],
      };
    }

    case 'SET_ACTIVE_SESSION':
      return { ...state, activeSessionId: action.payload, streamProgress: [] };

    case 'ADD_SESSION': {
      const newSession = action.payload;
      return {
        ...state,
        sessions: [newSession, ...state.sessions],
        activeSessionId: newSession.session_id,
        messagesBySession: { ...state.messagesBySession, [newSession.session_id]: [] },
      };
    }

    case 'REMOVE_SESSION': {
      const sid = action.payload;
      const { [sid]: _, ...rest } = state.messagesBySession;
      return {
        ...state,
        sessions: state.sessions.filter((s) => s.session_id !== sid),
        messagesBySession: rest,
        activeSessionId: state.activeSessionId === sid ? null : state.activeSessionId,
      };
    }

    case 'CLEAR_STUDENT_DATA': {
      const targetStudentId = action.payload || state.activeStudentId;
      const remainingSessions = state.sessions.filter(
        (session) => session.student_id !== targetStudentId
      );
      const remainingSessionIds = new Set(remainingSessions.map((session) => session.session_id));
      const nextMessagesBySession = Object.fromEntries(
        Object.entries(state.messagesBySession).filter(([sessionId]) => remainingSessionIds.has(sessionId))
      );
      const nextActiveSessionId = remainingSessionIds.has(state.activeSessionId)
        ? state.activeSessionId
        : (remainingSessions[0]?.session_id || null);
      return {
        ...state,
        sessions: remainingSessions,
        messagesBySession: nextMessagesBySession,
        activeSessionId: nextActiveSessionId,
        streamProgress: [],
      };
    }

    case 'CLEAR_ALL_LOCAL_DATA': {
      const runtimeId = getOrCreateRuntimeStudentId();
      return {
        ...state,
        profiles: [],
        activeStudentId: runtimeId,
        sessions: [],
        activeSessionId: null,
        messagesBySession: {},
        profile: null,
        profileLoading: false,
        streamProgress: [],
      };
    }

    case 'RENAME_SESSION': {
      const { sessionId: renameId, title } = action.payload;
      return {
        ...state,
        sessions: state.sessions.map((s) =>
          s.session_id === renameId ? { ...s, title } : s
        ),
      };
    }

    case 'TOGGLE_PIN_SESSION': {
      const pinId = action.payload;
      return {
        ...state,
        sessions: state.sessions.map((s) =>
          s.session_id === pinId ? { ...s, pinned: !s.pinned } : s
        ),
      };
    }

    case 'ADD_MESSAGE': {
      const { sessionId, message } = action.payload;
      const msgs = state.messagesBySession[sessionId] || [];
      return {
        ...state,
        messagesBySession: { ...state.messagesBySession, [sessionId]: [...msgs, message] },
      };
    }

    case 'UPDATE_LAST_MESSAGE': {
      const { sessionId, update } = action.payload;
      const msgs = [...(state.messagesBySession[sessionId] || [])];
      if (msgs.length > 0) {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...update };
      }
      return {
        ...state,
        messagesBySession: { ...state.messagesBySession, [sessionId]: msgs },
      };
    }

    case 'APPEND_MESSAGE_PROGRESS': {
      const { sessionId, progress } = action.payload;
      const msgs = [...(state.messagesBySession[sessionId] || [])];
      if (msgs.length > 0) {
        const last = { ...msgs[msgs.length - 1] };
        last.progress = [...(last.progress || []), progress];
        msgs[msgs.length - 1] = last;
      }
      return {
        ...state,
        messagesBySession: { ...state.messagesBySession, [sessionId]: msgs },
      };
    }

    case 'SET_STREAMING':
      return { ...state, isStreaming: action.payload };

    case 'ADD_PROGRESS':
      return { ...state, streamProgress: [...state.streamProgress, action.payload] };

    case 'CLEAR_PROGRESS':
      return { ...state, streamProgress: [] };

    case 'SET_PROFILE':
      return { ...state, profile: action.payload, profileLoading: false };

    case 'SET_PROFILE_LOADING':
      return { ...state, profileLoading: action.payload };

    case 'SET_SETTINGS':
      return { ...state, settings: { ...state.settings, ...action.payload } };

    case 'SET_THEME':
      return { ...state, theme: action.payload };

    case 'TOGGLE_SIDEBAR':
      return { ...state, sidebarOpen: !state.sidebarOpen };

    default:
      return state;
  }
}

// ── Provider ────────────────────────────────────────────────────

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);

  // Persist to localStorage whenever sessions/messages/settings/theme change
  useEffect(() => {
    persistState(state);
  }, [state.profiles, state.activeStudentId, state.sessions, state.activeSessionId, state.messagesBySession, state.settings, state.theme]);

  // Apply theme on change
  useEffect(() => {
    applyTheme(state.theme);

    // Listen for system theme changes when theme is 'system'
    if (state.theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = () => applyTheme('system');
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }
  }, [state.theme]);

  // ── Auto-load profile on app start for personalization ──
  const profileLoaded = useRef(false);
  useEffect(() => {
    (async () => {
      try {
        dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
        const profiles = await getProfiles();
        dispatch({ type: 'SET_PROFILES', payload: profiles });

        const hasActive = profiles.some((profile) => profile.student_id === state.activeStudentId);
        const preferredStudentId = hasActive
          ? state.activeStudentId
          : (profiles[0]?.student_id || state.activeStudentId || getOrCreateRuntimeStudentId());

        if (!profileLoaded.current) {
          profileLoaded.current = true;
        }

        if (preferredStudentId !== state.activeStudentId) {
          dispatch({ type: 'SET_ACTIVE_STUDENT', payload: preferredStudentId });
        }

        const data = await getProfile(preferredStudentId);
        dispatch({ type: 'SET_PROFILE', payload: data });
      } catch {
        dispatch({ type: 'SET_PROFILE_LOADING', payload: false });
      }
    })();
  }, [state.activeStudentId]);

  const refreshProfile = useCallback(async (studentId) => {
    dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
    const data = await getProfile(studentId);
    dispatch({ type: 'SET_PROFILE', payload: data });
    return data;
  }, []);

  const refreshProfiles = useCallback(async () => {
    const profiles = await getProfiles();
    dispatch({ type: 'SET_PROFILES', payload: profiles });
    return profiles;
  }, []);

  const switchStudent = useCallback(async (studentId) => {
    dispatch({ type: 'SET_ACTIVE_STUDENT', payload: studentId });
    await refreshProfile(studentId);
  }, [refreshProfile]);

  const createProfile = useCallback(async (profileInput) => {
    const created = await createProfileRequest(profileInput);
    await refreshProfiles();
    dispatch({ type: 'SET_ACTIVE_STUDENT', payload: created.student_id });
    await refreshProfile(created.student_id);
    return created;
  }, [refreshProfile, refreshProfiles]);

  const createSession = useCallback(() => {
    const sessionId = `session_${Date.now().toString(36)}`;
    dispatch({
      type: 'ADD_SESSION',
      payload: {
        session_id: sessionId,
        student_id: state.activeStudentId,
        title: 'New Chat',
        created_at: new Date().toISOString(),
      },
    });
    return sessionId;
  }, [state.activeStudentId]);

  const value = { state, dispatch, createSession, refreshProfile, refreshProfiles, switchStudent, createProfile };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
}
