/**
 * Pathfinder API client.
 * Handles all backend communication including SSE streaming.
 */

const API_BASE = '/api/v1';

// ── SSE Chat ────────────────────────────────────────────────────

/**
 * Send a chat message and receive SSE stream.
 * @param {Object} params - { query, sessionId, files, isGlobalUpload }
 * @param {Object} callbacks - { onProgress, onToken, onDone, onError }
 * @returns {AbortController} - call .abort() to cancel
 */
export function chatSSE({ query, sessionId, files = [], isGlobalUpload = false }, callbacks) {
  const controller = new AbortController();

  const formData = new FormData();
  formData.append('query', query);
  if (sessionId) formData.append('session_id', sessionId);
  formData.append('is_global_upload', isGlobalUpload.toString());
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

export async function uploadDocument(file, scope = 'global', sessionId = null) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('scope', scope);
  if (sessionId) formData.append('session_id', sessionId);

  const response = await fetch(`${API_BASE}/documents`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  return response.json();
}

// ── Profile ─────────────────────────────────────────────────────

export async function getProfile() {
  const response = await fetch(`${API_BASE}/profile`);
  if (!response.ok) throw new Error(`Failed to load profile: ${response.status}`);
  return response.json();
}

export async function updateProfile(field, value) {
  const response = await fetch(`${API_BASE}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field, value }),
  });
  if (!response.ok) throw new Error(`Failed to update profile: ${response.status}`);
  return response.json();
}

export async function deleteProfileEntity(label, name) {
  const response = await fetch(`${API_BASE}/profile/entity/${label}/${name}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error(`Failed to delete entity: ${response.status}`);
  return response.json();
}

export async function addProfileText(text) {
  const response = await fetch(`${API_BASE}/profile/text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error(`Failed to add profile text: ${response.status}`);
  return response.json();
}

export async function getProfileGraph() {
  const response = await fetch(`${API_BASE}/profile/graph`);
  if (!response.ok) throw new Error(`Failed to load graph: ${response.status}`);
  return response.json();
}

export async function resetAllData() {
  const response = await fetch(`${API_BASE}/profile/reset`, { method: 'DELETE' });
  if (!response.ok) throw new Error(`Failed to reset data: ${response.status}`);
  return response.json();
}

// ── Sessions ────────────────────────────────────────────────────

export async function getSessions() {
  const response = await fetch(`${API_BASE}/sessions`);
  if (!response.ok) throw new Error(`Failed to load sessions: ${response.status}`);
  return response.json();
}

export async function deleteSession(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
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
