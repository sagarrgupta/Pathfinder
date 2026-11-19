import React, { useEffect, useState } from 'react';

function formatDuration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m ${seconds % 60}s`;
  if (minutes) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

export default function ResponseTime({ timing, isStreaming }) {
  const [now, setNow] = useState(Date.now);
  const isRunning = isStreaming && timing?.elapsedMs == null;

  useEffect(() => {
    if (!isRunning || !timing?.startedAt) return undefined;
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [isRunning, timing?.startedAt]);

  // Old messages have no timing data; never invent a duration for them.
  if (!timing || (!isRunning && timing.elapsedMs == null)) return null;
  const elapsed = timing.elapsedMs ?? (now - timing.startedAt);
  const label = isRunning ? 'Working for' : timing.status === 'stopped'
    ? 'Stopped after' : timing.status === 'error' ? 'Failed after' : 'Worked for';

  return (
    <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground" title="Time from sending your request until completion, including upload and network time">
      {label} {formatDuration(elapsed)}
    </span>
  );
}
