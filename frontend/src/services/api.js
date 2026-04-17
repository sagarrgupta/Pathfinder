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
 * @param {Object} params - { query, sessionId, files, reasoning }
 * @param {Object} callbacks - { onProgress, onToken, onDone, onError }
 * @returns {AbortController} - call .abort() to cancel
 */
export function chatSSE({ query, sessionId, studentId, files = [], replaceFilenames = [], reasoning = 'medium' }, callbacks) {
  const controller = new AbortController();

  const formData = new FormData();
  formData.append('query', query);
  if (sessionId) formData.append('session_id', sessionId);
  if (studentId) formData.append('student_id', studentId);
  formData.append('reasoning', reasoning);
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

export async function uploadDocument(file, replace = false, studentId = null) {
  const formData = new FormData();
  formData.append('file', file);
  if (studentId) formData.append('student_id', studentId);
  if (replace) formData.append('replace', 'true');

  const response = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  return response.json();
}

// ── Student ─────────────────────────────────────────────────────

export async function getStudents() {
  const response = await fetch(`${API_BASE}/students`);
  if (!response.ok) throw new Error(`Failed to load students: ${response.status}`);
  return response.json();
}

export async function createStudent(student) {
  const response = await fetch(`${API_BASE}/students`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(student),
  });
  if (!response.ok) throw new Error(`Failed to create student: ${response.status}`);
  return response.json();
}

export async function getStudent(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/student`, studentId));
  if (!response.ok) throw new Error(`Failed to load student: ${response.status}`);
  return response.json();
}

export async function updateStudent(field, value, studentId) {
  const response = await fetch(`${API_BASE}/student`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field, value, student_id: studentId }),
  });
  if (!response.ok) throw new Error(`Failed to update student: ${response.status}`);
  return response.json();
}

export async function resetStudentData(studentId) {
  const response = await fetch(withStudentId(`${API_BASE}/student/reset`, studentId), { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to reset data: ${response.status}`);
  return response.json();
}

export async function deleteAllDataEverywhere() {
  const response = await fetch(`${API_BASE}/settings/delete-all-data`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to delete all data: ${response.status}`);
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

// ── Replay Artifacts ────────────────────────────────────────────

export async function getReplays(limit = 25) {
  const response = await fetch(`${API_BASE}/replays?limit=${encodeURIComponent(limit)}`);
  if (!response.ok) throw new Error(`Failed to load replays: ${response.status}`);
  return response.json();
}

export async function getReplay(replayId) {
  const response = await fetch(`${API_BASE}/replays/${encodeURIComponent(replayId)}`);
  if (!response.ok) throw new Error(`Failed to load replay: ${response.status}`);
  return response.json();
}
