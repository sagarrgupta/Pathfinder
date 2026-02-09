import React, { useRef, useEffect } from 'react';
import { Sparkles } from 'lucide-react';
import Message from './Message';

function TypingIndicator() {
  return (
    <div className="flex gap-3 justify-start animate-fade-in-up">
      <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center flex-shrink-0 ring-1 ring-primary/10">
        <Sparkles className="h-5 w-5 text-primary" />
      </div>
      <div className="rounded-lg px-4 py-3 bg-muted">
        <div className="flex items-center gap-1.5 h-5">
          <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground/50" />
          <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground/50" />
          <span className="typing-dot w-2 h-2 rounded-full bg-muted-foreground/50" />
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4 animate-fade-in">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary/15 to-primary/5 ring-1 ring-primary/10 flex items-center justify-center mb-4">
        <Sparkles className="h-7 w-7 text-primary/70" />
      </div>
      <p className="text-muted-foreground text-sm max-w-xs">
        Start a conversation by typing your question below.
        I can help with academics, career planning, and interview prep.
      </p>
    </div>
  );
}

export default function MessageList({ messages, isStreaming }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  if (messages.length === 0) {
    return <EmptyState />;
  }

  // Check if the last message is an empty assistant message (still loading)
  const lastMsg = messages[messages.length - 1];
  const showTyping = isStreaming && lastMsg?.role === 'assistant' && !lastMsg.content && (!lastMsg.progress || lastMsg.progress.length === 0);

  return (
    <div className="max-w-[85%] mx-auto px-4 py-6 space-y-6">
      {messages.map((msg, idx) => (
        <div key={idx} className="animate-fade-in-up" style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}>
          <Message key={idx} message={msg} isLast={idx === messages.length - 1} isStreaming={isStreaming} />
        </div>
      ))}
      {showTyping && <TypingIndicator />}
      <div ref={endRef} />
    </div>
  );
}
