import React, { useState, useRef, useEffect } from 'react';
import { Send, Square, Paperclip, X } from 'lucide-react';
import { cn } from '@/lib/utils';

const REASONING_OPTIONS = [
  { value: 'off', label: 'Off' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

export default function InputArea({
  onSend,
  onStop,
  isStreaming,
  files,
  onFilesChange,
  reasoning,
  onReasoningChange,
}) {
  const [input, setInput] = useState('');
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, [input]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const hasText = input.trim();
    const hasFiles = files.length > 0;
    if (hasText || hasFiles) {
      const message = hasText ? input.trim() : `Please process the uploaded file(s): ${files.map((f) => f.name).join(', ')}`;
      onSend(message);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleFileSelect = (e) => {
    const selected = Array.from(e.target.files || []);
    onFilesChange([...files, ...selected]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (index) => {
    onFilesChange(files.filter((_, i) => i !== index));
  };

  const placeholder = files.length > 0
    ? 'Tell Pathfinder what to do with these files...'
    : 'Ask about courses, jobs, interviews, or anything tied to your profile and documents...';

  return (
    <div className="bg-card/70 px-3 py-5 backdrop-blur-sm md:px-4 lg:px-5">
      <div className="mx-auto max-w-[1120px]">
        <div className="space-y-2">

          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 animate-fade-in">
              {files.map((file, i) => (
                <div key={i} className="flex items-center gap-1.5 rounded-xl border border-border/70 bg-muted/35 px-3 py-2 text-sm">
                  <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="max-w-[180px] truncate">{file.name}</span>
                  <button
                    onClick={() => removeFile(i)}
                    className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="rounded-[30px] border border-border/80 bg-background px-5 py-3 shadow-[0_10px_30px_rgba(15,23,42,0.06)]">
              <div className="relative">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={placeholder}
                  rows={1}
                  className="block min-h-[72px] max-h-[160px] w-full resize-none bg-transparent px-0 py-0 text-[16px] leading-relaxed text-foreground placeholder:text-muted-foreground/70 focus:outline-none"
                  disabled={isStreaming}
                />
                {input.length > 0 && (
                  <span className="pointer-events-none absolute bottom-0 right-0 select-none text-[10px] text-muted-foreground/45">
                    Shift+Enter for new line
                  </span>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    title="Attach file (PDF, Image, DOCX)"
                  >
                    <Paperclip className="h-4.5 w-4.5" />
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg,.heif,.heic,.docx"
                    multiple
                    onChange={handleFileSelect}
                    className="hidden"
                  />
                  <div className="flex items-center gap-1.5 h-9 rounded-full border border-border/70 bg-muted/20 px-3 text-[11px] text-foreground">
                    <span className="text-muted-foreground">Reasoning:</span>
                    <select
                      value={reasoning || 'medium'}
                      onChange={(e) => onReasoningChange?.(e.target.value)}
                      className="bg-transparent text-foreground outline-none"
                      title="Choose the model reasoning level"
                    >
                      {REASONING_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {isStreaming ? (
                    <button
                      type="button"
                      onClick={onStop}
                      className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-muted text-foreground transition-all hover:bg-accent active:scale-95"
                      title="Stop generating"
                    >
                      <Square className="h-4.5 w-4.5" />
                    </button>
                  ) : (
                    <button
                      type="submit"
                      disabled={!input.trim() && files.length === 0}
                      className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-all hover:opacity-90 disabled:opacity-35 active:scale-95"
                      title="Send message"
                    >
                      <Send className="h-4.5 w-4.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
