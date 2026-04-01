import React, { useState, useRef, useEffect } from 'react';
import { Send, Square, Paperclip, X, Globe, Columns2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function InputArea({
  onSend,
  onStop,
  isStreaming,
  files,
  onFilesChange,
  isGlobalUpload,
  onGlobalUploadChange,
  compareMode,
  onCompareModeChange,
  textModel,
  textModelOptions,
  onTextModelChange,
}) {
  const [input, setInput] = useState('');
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  // Auto-resize textarea
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
      const message = hasText ? input.trim() : `Please process the uploaded file(s): ${files.map(f => f.name).join(', ')}`;
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

  return (
    <div className="border-t bg-card/80 backdrop-blur-sm p-4">
      <div className="max-w-[85%] mx-auto">
        {/* Attached files */}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3 animate-fade-in">
            {files.map((file, i) => (
              <div key={i} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted text-sm border border-border/50">
                <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="truncate max-w-[180px]">{file.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-destructive/10 hover:text-destructive transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
            {/* Global upload toggle */}
            <button
              onClick={() => onGlobalUploadChange(!isGlobalUpload)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                isGlobalUpload
                  ? 'bg-primary/10 text-primary border border-primary/20'
                  : 'bg-muted text-muted-foreground hover:bg-accent border border-border/50'
              )}
              title={isGlobalUpload ? 'Documents will be added to your global profile' : 'Documents will only be used in this chat session'}
            >
              <Globe className="h-3.5 w-3.5" />
              {isGlobalUpload ? 'Global' : 'Session only'}
            </button>
          </div>
        )}

        {/* Input form */}
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          {/* File upload button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="h-[44px] w-[44px] flex items-center justify-center rounded-xl border bg-background hover:bg-accent transition-colors flex-shrink-0"
            title="Attach file (PDF, Image, DOCX)"
          >
            <Paperclip className="h-5 w-5 text-muted-foreground" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.heif,.heic,.docx"
            multiple
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* Text input */}
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about academics, career, or interview prep..."
              rows={1}
              className="block w-full resize-none rounded-xl border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50 min-h-[44px] max-h-[160px] transition-shadow"
              disabled={isStreaming}
            />
            {/* Shift+Enter hint */}
            {input.length > 0 && (
              <span className="absolute right-3 bottom-1.5 text-[10px] text-muted-foreground/50 pointer-events-none select-none">
                Shift+Enter for new line
              </span>
            )}
          </div>

          {/* Send / Stop button */}
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="h-[44px] w-[44px] flex items-center justify-center rounded-xl bg-destructive text-destructive-foreground hover:opacity-90 transition-all flex-shrink-0 active:scale-95"
              title="Stop generating"
            >
              <Square className="h-5 w-5" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() && files.length === 0}
              className="h-[44px] w-[44px] flex items-center justify-center rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-all disabled:opacity-40 flex-shrink-0 active:scale-95"
              title="Send message"
            >
              <Send className="h-5 w-5" />
            </button>
          )}
        </form>

        <div className="flex flex-col gap-2 mt-3 px-1 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded-xl border bg-background/80 p-1 shadow-sm">
              <label className="px-2 text-[11px] font-medium text-muted-foreground">
                Model
              </label>
              <select
                value={textModel}
                onChange={(event) => onTextModelChange(event.target.value)}
                disabled={isStreaming}
                className="min-w-[180px] appearance-none rounded-lg border-0 bg-transparent px-2 py-1.5 text-xs font-medium text-foreground focus:outline-none focus:ring-0 disabled:opacity-50"
              >
                {(textModelOptions || []).map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              onClick={() => onCompareModeChange(!compareMode)}
              disabled={isStreaming || files.length > 0}
              className={cn(
                'inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-colors shadow-sm',
                compareMode
                  ? 'border-primary/30 bg-primary/10 text-primary'
                  : 'border-border/50 bg-background/80 text-muted-foreground hover:bg-accent',
                (isStreaming || files.length > 0) && 'cursor-not-allowed opacity-50'
              )}
              title={files.length > 0 ? 'Upload files first, then run compare mode' : 'Run all retrieval modes and compare answers'}
            >
              <Columns2 className="h-3.5 w-3.5" />
              {compareMode ? 'Compare Mode On' : 'Compare Retrieval Modes'}
            </button>
          </div>

          <span className="text-[11px] text-muted-foreground">
            {compareMode
              ? 'Runs Embedding, Hybrid, and PageIndex side-by-side.'
              : 'Single answer using the selected retrieval mode and chosen model.'}
          </span>
        </div>
      </div>
    </div>
  );
}
