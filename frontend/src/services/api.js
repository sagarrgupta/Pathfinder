/**
 * Pathfinder API client.
 * Handles all backend communication including SSE streaming.
 */

const API_BASE = '/api/v1';

function withStudentId(path, studentId) {
  if (!studentId) return path;
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}student_id=${encodeURIComponent(studentId)}`;
}

// ── SSE Chat ────────────────────────────────────────────────────

/**
 * Send a chat message and receive SSE stream.
 * @param {Object} params - { query, sessionId, files, isGlobalUpload }
 * @param {Object} callbacks - { onProgress, onToken, onDone, onError }
 * @returns {AbortController} - call .abort() to cancel
 */
export function chatSSE({ query, sessionId, studentId, files = [], isGlobalUpload = false, replaceFilenames = [] }, callbacks) {
  const controller = new AbortController();

  const formData = new FormData();
  formData.append('query', query);
  if (sessionId) formData.append('session_id', sessionId);
  if (studentId) formData.append('student_id', studentId);
  formData.append('is_global_upload', isGlobalUpload.toString());
  if (replaceFilenames.length > 0) {
    formData.append('replace_filenames', replaceFilenames.join(','));
  }
  files.forEach((file) => formData.append('files', file));

  fetch(`${API_BASE}/chat`, {
    method: 'POST',
    body: formData,
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      callbacks.onError?.(`Server error: ${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (eventType === 'progress') callbacks.onProgress?.(data);
            else if (eventType === 'token') callbacks.onToken?.(data);
            else if (eventType === 'done') callbacks.onDone?.(data);
            else if (eventType === 'error') callbacks.onError?.(data.error);
          } catch {
            // skip malformed JSON
          }
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      callbacks.onError?.(err.message);
    }
  });

  return controller;
}

// ── Document Upload ─────────────────────────────────────────────

export async function checkDocumentExists(filename, studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/documents/check?filename=${encodeURIComponent(filename)}`, studentId));
  if (!response.ok) throw new Error(`Check failed: ${response.status}`);
  return response.json();
}

export async function uploadDocument(file, scope = 'global', sessionId = null, replace = false, studentId = null) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('scope', scope);
  if (sessionId) formData.append('session_id', sessionId);
  if (studentId) formData.append('student_id', studentId);
  if (replace) formData.append('replace', 'true');

  const response = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  return response.json();
}

// ── Profile ─────────────────────────────────────────────────────

export async function getProfiles() {
  const response = await fetch(`${API_BASE}/profiles`);
  if (!response.ok) throw new Error(`Failed to load profiles: ${response.status}`);
  return response.json();
}

export async function createProfile(profile) {
  const response = await fetch(`${API_BASE}/profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
  if (!response.ok) throw new Error(`Failed to create profile: ${response.status}`);
  return response.json();
}

export async function getProfile(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile`, studentId));
  if (!response.ok) throw new Error(`Failed to load profile: ${response.status}`);
  return response.json();
}

export async function updateProfile(field, value, studentId) {
  const response = await fetch(`${API_BASE}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field, value, student_id: studentId }),
  });
  if (!response.ok) throw new Error(`Failed to update profile: ${response.status}`);
  return response.json();
}

export async function deleteProfileEntity(label, name, studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/entity/${label}/${name}`, studentId), {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error(`Failed to delete entity: ${response.status}`);
  return response.json();
}

export async function updateProfileEntity(label, name, properties, studentId) {
  const response = await fetch(`${API_BASE}/profile/entity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, name, properties, student_id: studentId }),
  });
  if (!response.ok) throw new Error(`Failed to update entity: ${response.status}`);
  return response.json();
}

export async function addProfileText(text, studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/text`, studentId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error(`Failed to add profile text: ${response.status}`);
  return response.json();
}

export async function getProfileGraph(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/graph`, studentId));
  if (!response.ok) throw new Error(`Failed to load graph: ${response.status}`);
  return response.json();
}

export async function getProfileConflicts(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/conflicts`, studentId));
  if (!response.ok) throw new Error(`Failed to load conflicts: ${response.status}`);
  return response.json();
}

export async function autoResolveProfileConflicts(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/conflicts/self-resolve`, studentId), {
    method: 'POST',
  });
  if (!response.ok) throw new Error(`Failed to resolve conflicts: ${response.status}`);
  return response.json();
}

export async function selfResolveProfileConflicts(studentId) {
  return autoResolveProfileConflicts(studentId);
}

export async function resolveConflictChoice(payload) {
  const response = await fetch(`${API_BASE}/profile/conflicts/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Failed to apply conflict choice: ${response.status}`);
  return response.json();
}

export async function resetAllData(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/profile/reset`, studentId), { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to reset data: ${response.status}`);
  return response.json();
}

export async function deleteAllDataEverywhere() {
  const response = await fetch(`${API_BASE}/settings/delete-all-data`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to delete all data: ${response.status}`);
  return response.json();
}

// ── Sessions ────────────────────────────────────────────────────

export async function getSessions(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/sessions`, studentId));
  if (!response.ok) throw new Error(`Failed to load sessions: ${response.status}`);
  return response.json();
}

export async function deleteSession(sessionId, studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/sessions/${sessionId}`, studentId), { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to delete session: ${response.status}`);
  return response.json();
}

// ── Settings ────────────────────────────────────────────────────

export async function getSettings() {
  const response = await fetch(`${API_BASE}/settings`);
  if (!response.ok) throw new Error(`Failed to load settings: ${response.status}`);
  return response.json();
}

export async function updateSettings(updates) {
  const response = await fetch(`${API_BASE}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!response.ok) throw new Error(`Failed to update settings: ${response.status}`);
  return response.json();
}

// ── Health ──────────────────────────────────────────────────────

export async function getHealth() {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  return response.json();
}
