import React, { createContext, useContext, useEffect, useReducer, useRef } from 'react';
import { createProfile, getProfile, getProfiles, getSavedRecommendations } from '@/services/api';

const AppContext = createContext(null);
const STORAGE_KEY = 'pathfinder_state_v2';

function loadPersistedState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function persistState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      profiles: state.profiles,
      activeStudentId: state.activeStudentId,
      sessionsByStudent: state.sessionsByStudent,
      activeSessionByStudent: state.activeSessionByStudent,
      messagesByStudent: state.messagesByStudent,
      settings: state.settings,
      theme: state.theme,
    }));
  } catch {
    // ignore persistence failures
  }
}

function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  const resolved = theme === 'system' ? getSystemTheme() : theme;
  document.documentElement.classList.toggle('dark', resolved === 'dark');
}

const persisted = loadPersistedState();

const initialState = {
  profiles: persisted?.profiles || [],
  activeStudentId: persisted?.activeStudentId || null,
  sessionsByStudent: persisted?.sessionsByStudent || {},
  activeSessionByStudent: persisted?.activeSessionByStudent || {},
  messagesByStudent: persisted?.messagesByStudent || {},
  settings: persisted?.settings || { topic_guard_enabled: true },
  theme: persisted?.theme || 'system',
  profile: null,
  savedRecommendations: [],
  profileLoading: false,
  sidebarOpen: true,
  isStreaming: false,
};

function ensureStudentState(container, studentId, fallback) {
  return container[studentId] || fallback;
}

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_PROFILES':
      return { ...state, profiles: action.payload };
    case 'ADD_PROFILE':
      return { ...state, profiles: [action.payload, ...state.profiles] };
    case 'REMOVE_PROFILE': {
      const { studentId } = action.payload;
      return {
        ...state,
        profiles: state.profiles.filter((profile) => profile.student_id !== studentId),
      };
    }
    case 'SET_ACTIVE_STUDENT':
      if (!action.payload) {
        return {
          ...state,
          activeStudentId: null,
          profile: null,
          savedRecommendations: [],
        };
      }
      return {
        ...state,
        activeStudentId: action.payload,
        profile: null,
        savedRecommendations: [],
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [action.payload]: ensureStudentState(state.sessionsByStudent, action.payload, []),
        },
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [action.payload]: state.activeSessionByStudent[action.payload] || null,
        },
        messagesByStudent: {
          ...state.messagesByStudent,
          [action.payload]: ensureStudentState(state.messagesByStudent, action.payload, {}),
        },
        isStreaming: false,
      };
    case 'SET_ACTIVE_SESSION':
      return {
        ...state,
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [action.studentId]: action.payload,
        },
      };
    case 'ADD_SESSION': {
      const { studentId, session } = action.payload;
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: [session, ...ensureStudentState(state.sessionsByStudent, studentId, [])],
        },
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [studentId]: session.session_id,
        },
        messagesByStudent: {
          ...state.messagesByStudent,
          [studentId]: {
            ...ensureStudentState(state.messagesByStudent, studentId, {}),
            [session.session_id]: [],
          },
        },
      };
    }
    case 'SET_STUDENT_SESSIONS': {
      const { studentId, sessions } = action.payload;
      return {
        ...state,
        sessionsByStudent: { ...state.sessionsByStudent, [studentId]: sessions },
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [studentId]: sessions.some((session) => session.session_id === state.activeSessionByStudent[studentId])
            ? state.activeSessionByStudent[studentId]
            : sessions[0]?.session_id || null,
        },
      };
    }
    case 'RESET_STUDENT_LOCAL_DATA': {
      const { studentId } = action.payload;
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: [],
        },
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [studentId]: null,
        },
        messagesByStudent: {
          ...state.messagesByStudent,
          [studentId]: {},
        },
        savedRecommendations: state.activeStudentId === studentId ? [] : state.savedRecommendations,
        profile: state.activeStudentId === studentId ? null : state.profile,
        isStreaming: state.activeStudentId === studentId ? false : state.isStreaming,
      };
    }
    case 'REMOVE_SESSION': {
      const { studentId, sessionId } = action.payload;
      const studentMessages = { ...ensureStudentState(state.messagesByStudent, studentId, {}) };
      delete studentMessages[sessionId];
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: ensureStudentState(state.sessionsByStudent, studentId, []).filter((s) => s.session_id !== sessionId),
        },
        messagesByStudent: {
          ...state.messagesByStudent,
          [studentId]: studentMessages,
        },
        activeSessionByStudent: {
          ...state.activeSessionByStudent,
          [studentId]: state.activeSessionByStudent[studentId] === sessionId ? null : state.activeSessionByStudent[studentId],
        },
      };
    }
    case 'RENAME_SESSION': {
      const { studentId, sessionId, title } = action.payload;
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: ensureStudentState(state.sessionsByStudent, studentId, []).map((s) =>
            s.session_id === sessionId ? { ...s, title } : s
          ),
        },
      };
    }
    case 'TOGGLE_PIN_SESSION': {
      const { studentId, sessionId } = action.payload;
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: ensureStudentState(state.sessionsByStudent, studentId, []).map((s) =>
            s.session_id === sessionId ? { ...s, pinned: !s.pinned } : s
          ),
        },
      };
    }
    case 'ADD_MESSAGE': {
      const { studentId, sessionId, message } = action.payload;
      const studentMessages = { ...ensureStudentState(state.messagesByStudent, studentId, {}) };
      studentMessages[sessionId] = [...(studentMessages[sessionId] || []), message];
      return {
        ...state,
        sessionsByStudent: {
          ...state.sessionsByStudent,
          [studentId]: ensureStudentState(state.sessionsByStudent, studentId, []).map((session) =>
            session.session_id === sessionId
              ? {
                  ...session,
                  last_message: message.content || session.last_message || '',
                  updated_at: new Date().toISOString(),
                }
              : session
          ),
        },
        messagesByStudent: { ...state.messagesByStudent, [studentId]: studentMessages },
      };
    }
    case 'UPDATE_LAST_MESSAGE': {
      const { studentId, sessionId, update } = action.payload;
      const studentMessages = { ...ensureStudentState(state.messagesByStudent, studentId, {}) };
      const msgs = [...(studentMessages[sessionId] || [])];
      if (msgs.length > 0) msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...update };
      studentMessages[sessionId] = msgs;
      return {
        ...state,
        messagesByStudent: { ...state.messagesByStudent, [studentId]: studentMessages },
      };
    }
    case 'APPEND_MESSAGE_PROGRESS': {
      const { studentId, sessionId, progress } = action.payload;
      const studentMessages = { ...ensureStudentState(state.messagesByStudent, studentId, {}) };
      const msgs = [...(studentMessages[sessionId] || [])];
      if (msgs.length > 0) {
        const last = { ...msgs[msgs.length - 1] };
        last.progress = [...(last.progress || []), progress];
        msgs[msgs.length - 1] = last;
      }
      studentMessages[sessionId] = msgs;
      return {
        ...state,
        messagesByStudent: { ...state.messagesByStudent, [studentId]: studentMessages },
      };
    }
    case 'SET_STREAMING':
      return { ...state, isStreaming: action.payload };
    case 'SET_PROFILE':
      return { ...state, profile: action.payload, profileLoading: false };
    case 'SET_SAVED_RECOMMENDATIONS':
      return { ...state, savedRecommendations: action.payload };
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

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const bootstrapped = useRef(false);

  useEffect(() => {
    persistState(state);
  }, [
    state.profiles,
    state.activeStudentId,
    state.sessionsByStudent,
    state.activeSessionByStudent,
    state.messagesByStudent,
    state.settings,
    state.theme,
  ]);

  useEffect(() => {
    applyTheme(state.theme);
    if (state.theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = () => applyTheme('system');
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }
  }, [state.theme]);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    (async () => {
      let profiles = [];
      try {
        profiles = await getProfiles();
      } catch {
        profiles = [];
      }
      if (profiles.length === 0) {
        try {
          const created = await createProfile({ name: 'Student' });
          profiles = [created];
        } catch {
          profiles = [];
        }
      }
      dispatch({ type: 'SET_PROFILES', payload: profiles });
      const persistedActive = state.activeStudentId;
      const activeStudentId = profiles.some((profile) => profile.student_id === persistedActive)
        ? persistedActive
        : profiles[0]?.student_id || null;
      if (activeStudentId) {
        dispatch({ type: 'SET_ACTIVE_STUDENT', payload: activeStudentId });
      }
    })();
  }, [state.activeStudentId]);

  useEffect(() => {
    if (!state.activeStudentId) return;
    (async () => {
      try {
        dispatch({ type: 'SET_PROFILE_LOADING', payload: true });
        const [profileData, recommendationData] = await Promise.all([
          getProfile(state.activeStudentId),
          getSavedRecommendations(state.activeStudentId).catch(() => []),
        ]);
        dispatch({ type: 'SET_PROFILE', payload: profileData });
        dispatch({ type: 'SET_SAVED_RECOMMENDATIONS', payload: recommendationData });
      } catch {
        dispatch({ type: 'SET_PROFILE_LOADING', payload: false });
      }
    })();
  }, [state.activeStudentId]);

  const activeStudentId = state.activeStudentId;
  const sessions = activeStudentId ? ensureStudentState(state.sessionsByStudent, activeStudentId, []) : [];
  const activeSessionId = activeStudentId ? state.activeSessionByStudent[activeStudentId] || null : null;
  const messagesBySession = activeStudentId ? ensureStudentState(state.messagesByStudent, activeStudentId, {}) : {};

  const createSession = () => {
    if (!activeStudentId) return null;
    const session = {
      session_id: `session_${Date.now().toString(36)}`,
      student_id: activeStudentId,
      title: 'New Chat',
      created_at: new Date().toISOString(),
    };
    dispatch({ type: 'ADD_SESSION', payload: { studentId: activeStudentId, session } });
    return session.session_id;
  };

  const createProfileAndActivate = async (name = 'Student') => {
    const profile = await createProfile({ name });
    dispatch({ type: 'ADD_PROFILE', payload: profile });
    dispatch({ type: 'SET_ACTIVE_STUDENT', payload: profile.student_id });
    return profile;
  };

  const value = {
    state: {
      ...state,
      sessions,
      activeSessionId,
      messagesBySession,
      activeStudentId,
    },
    dispatch,
    createSession,
    createProfileAndActivate,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used within AppProvider');
  return context;
}
