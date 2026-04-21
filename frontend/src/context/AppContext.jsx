import React, { createContext, useContext, useReducer, useCallback, useEffect, useRef } from 'react';
import { createStudent as createStudentRequest, getStudent, getStudents } from '@/services/api';

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

function generateSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `session_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
  }
  return `session_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
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
        students: saved.students || [],
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
      students: state.students,
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
  students: persisted?.students || [],
  activeStudentId: persisted?.activeStudentId || getOrCreateRuntimeStudentId(),
  // Sessions (restored from localStorage if available)
  sessions: persisted?.sessions || [],
  activeSessionId: persisted?.activeSessionId || null,

  // Messages per session: { [sessionId]: [{role, content, metadata}] }
  messagesBySession: persisted?.messagesBySession || {},

  // Student graph
  student: null,
  studentLoading: false,

  // Settings
  settings: persisted?.settings || { topic_guard_enabled: true, reasoning: 'medium' },

  // Theme
  theme: persisted?.theme || 'system',

  // UI (never persisted)
  sidebarOpen: true,
  isStreaming: false,
};

// ── Reducer ─────────────────────────────────────────────────────

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_STUDENTS':
      return { ...state, students: action.payload };

    case 'SET_ACTIVE_STUDENT': {
      const nextStudentId = action.payload;
      const nextSessions = state.sessions.filter((s) => s.student_id === nextStudentId);
      return {
        ...state,
        activeStudentId: nextStudentId,
        activeSessionId: nextSessions[0]?.session_id || null,
      };
    }

    case 'SET_ACTIVE_SESSION':
      return { ...state, activeSessionId: action.payload };

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
      const remainingSessions = state.sessions.filter((s) => s.session_id !== sid);
      const preferredReplacement =
        remainingSessions.find((s) => s.student_id === state.activeStudentId) ||
        remainingSessions[0] ||
        null;
      const { [sid]: _, ...rest } = state.messagesBySession;
      return {
        ...state,
        sessions: remainingSessions,
        messagesBySession: rest,
        activeSessionId:
          state.activeSessionId === sid
            ? (preferredReplacement?.session_id || null)
            : state.activeSessionId,
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
      };
    }

    case 'CLEAR_ALL_LOCAL_DATA': {
      const runtimeId = getOrCreateRuntimeStudentId();
      return {
        ...state,
        students: [],
        activeStudentId: runtimeId,
        sessions: [],
        activeSessionId: null,
        messagesBySession: {},
        student: null,
        studentLoading: false,
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

    case 'SET_STUDENT':
      return { ...state, student: action.payload, studentLoading: false };

    case 'SET_STUDENT_LOADING':
      return { ...state, studentLoading: action.payload };

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

  // Persist to localStorage, but debounce writes so token streaming does not
  // serialize the entire app state on every SSE chunk.
  useEffect(() => {
    const delayMs = state.isStreaming ? 750 : 150;
    const timerId = window.setTimeout(() => {
      persistState(state);
    }, delayMs);
    return () => window.clearTimeout(timerId);
  }, [state.students, state.activeStudentId, state.sessions, state.activeSessionId, state.messagesBySession, state.settings, state.theme, state.isStreaming]);

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

  // ── Load students list once on mount ──
  const studentLoaded = useRef(false);
  useEffect(() => {
    if (studentLoaded.current) return;
    (async () => {
      try {
        const students = await getStudents();
        dispatch({ type: 'SET_STUDENTS', payload: students });
        studentLoaded.current = true;

        const hasActive = students.some((item) => item.student_id === state.activeStudentId);
        const preferredStudentId = hasActive
          ? state.activeStudentId
          : (students[0]?.student_id || state.activeStudentId || getOrCreateRuntimeStudentId());

        if (preferredStudentId !== state.activeStudentId) {
          dispatch({ type: 'SET_ACTIVE_STUDENT', payload: preferredStudentId });
        }
      } catch {
        // students failed to load; student effect will surface its own error
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch student whenever the active student changes ──
  useEffect(() => {
    if (!state.activeStudentId) return;
    let cancelled = false;
    (async () => {
      try {
        dispatch({ type: 'SET_STUDENT_LOADING', payload: true });
        const data = await getStudent(state.activeStudentId);
        if (!cancelled) {
          dispatch({ type: 'SET_STUDENT', payload: data });
        }
      } catch {
        if (!cancelled) {
          dispatch({ type: 'SET_STUDENT_LOADING', payload: false });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state.activeStudentId]);

  const refreshStudent = useCallback(async (studentId) => {
    dispatch({ type: 'SET_STUDENT_LOADING', payload: true });
    try {
      const data = await getStudent(studentId);
      dispatch({ type: 'SET_STUDENT', payload: data });
      return data;
    } catch (error) {
      dispatch({ type: 'SET_STUDENT_LOADING', payload: false });
      throw error;
    }
  }, []);

  const refreshStudents = useCallback(async () => {
    const students = await getStudents();
    dispatch({ type: 'SET_STUDENTS', payload: students });
    return students;
  }, []);

  const switchStudent = useCallback((studentId) => {
    // Dispatching SET_ACTIVE_STUDENT triggers the activeStudentId effect to load the student snapshot.
    dispatch({ type: 'SET_ACTIVE_STUDENT', payload: studentId });
  }, []);

  const createStudent = useCallback(async (studentInput) => {
    const created = await createStudentRequest(studentInput);
    await refreshStudents();
    dispatch({ type: 'SET_ACTIVE_STUDENT', payload: created.student_id });
    // The activeStudentId effect will load the new student automatically.
    return created;
  }, [refreshStudents]);

  const createSession = useCallback(() => {
    const sessionId = generateSessionId();
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

  const value = { state, dispatch, createSession, refreshStudent, refreshStudents, switchStudent, createStudent };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
}
