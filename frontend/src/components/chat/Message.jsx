import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  User, Sparkles, ChevronDown, ChevronUp, ExternalLink,
  Shield, Copy, Check, Loader2, CheckCircle2, Paperclip,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// Map technical node names to user-friendly phase labels
const STEP_LABELS = {
  input_guard: 'Validation',
  orchestrator: 'Planning',
  clarifier: 'Clarifying',
  doc_analyst: 'Documents',
  profile_manager: 'Your Profile',
  web_researcher: 'Research',
  academic_advisor: 'Academic Advice',
  career_planner: 'Career',
  interview_prep: 'Interview Prep',
  evaluator: 'Quality Check',
  responder: 'Response',
};

function formatStep(step) {
  const label = STEP_LABELS[step.node] || step.node;
  return { label, message: step.message || '' };
}

export default function Message({ message, isLast, isStreaming }) {
  const [showCitations, setShowCitations] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const metadata = message.metadata || {};
  const citations = metadata.citations || [];
  const progress = message.progress || [];
  const attachments = message.attachments || [];
  const isCurrentlyStreaming = isLast && isStreaming && !isUser;
  const hasContent = !!message.content;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = message.content || '';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className={cn('flex gap-3', isUser ? 'justify-end' : 'justify-start')}>
      {/* Bot Avatar */}
      {!isUser && (
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center flex-shrink-0 mt-1 ring-1 ring-primary/10">
          <Sparkles className="h-4.5 w-4.5 text-primary" />
        </div>
      )}

      {/* Content */}
      <div className={cn(
        'group rounded-2xl px-4 py-3 transition-colors',
        isUser
          ? 'max-w-[75%] bg-primary text-primary-foreground'
          : 'max-w-full bg-muted/70'
      )}>
        {/* ── Collapsible Progress (bot only) ── */}
        {!isUser && progress.length > 0 && (
          <div className="mb-3">
            {/* During streaming: show live progress */}
            {isCurrentlyStreaming && !hasContent ? (
              <div className="space-y-1.5">
                {progress.map((step, i) => {
                  const { label, message } = formatStep(step);
                  return (
                    <div key={i} className={cn(
                      'flex items-center gap-2 text-xs',
                      i === progress.length - 1 ? 'animate-fade-in' : ''
                    )}>
                      {i === progress.length - 1 ? (
                        <Loader2 className="h-3 w-3 animate-spin text-primary flex-shrink-0" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3 text-green-500 dark:text-green-400 flex-shrink-0" />
                      )}
                      <span className="font-medium text-foreground/70">{label}</span>
                      <span className="text-muted-foreground">{message}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* After streaming: collapsible summary */
              <div>
                <button
                  onClick={() => setShowProgress(!showProgress)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-accent/50"
                >
                  {showProgress ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  <span>See how I answered</span>
                </button>
                {showProgress && (
                  <div className="mt-2 pl-2 space-y-1 border-l-2 border-border/50 ml-0.5 animate-fade-in">
                    {progress.map((step, i) => {
                      const { label, message } = formatStep(step);
                      return (
                        <div key={i} className="flex items-center gap-2 text-xs pl-2">
                          <CheckCircle2 className="h-3 w-3 text-green-500 dark:text-green-400 flex-shrink-0" />
                          <span className="font-medium text-foreground/70">{label}</span>
                          <span className="text-muted-foreground">{message}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── File Attachments (user messages) ── */}
        {isUser && attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((file, i) => (
              <div
                key={i}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/15 text-xs font-medium"
              >
                <Paperclip className="h-3 w-3 flex-shrink-0 opacity-70" />
                <span className="truncate max-w-[160px]">{file.name}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Message Text ── */}
        {(hasContent || (!isCurrentlyStreaming)) && (
          <div className={cn(
            'max-w-none',
            isCurrentlyStreaming ? 'animate-pulse' : ''
          )}>
            {isUser ? (
              <p className="whitespace-pre-wrap leading-relaxed m-0">{message.content}</p>
            ) : (
              <div className="prose prose-sm dark:prose-invert max-w-none
                prose-headings:mt-3 prose-headings:mb-2 prose-headings:font-semibold
                prose-h1:text-lg prose-h2:text-base prose-h3:text-sm
                prose-p:my-1.5 prose-p:leading-relaxed
                prose-ul:my-1.5 prose-ol:my-1.5
                prose-li:my-0.5
                prose-table:my-2 prose-table:text-sm
                prose-th:px-3 prose-th:py-1.5 prose-th:bg-muted/50 prose-th:font-medium prose-th:text-left
                prose-td:px-3 prose-td:py-1.5 prose-td:border-t
                prose-strong:font-semibold
                prose-code:text-xs prose-code:bg-muted/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:font-mono
                prose-a:text-primary prose-a:no-underline hover:prose-a:underline
                prose-blockquote:border-primary/30 prose-blockquote:text-muted-foreground
                [&>*:first-child]:mt-0 [&>*:last-child]:mb-0
              ">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content || ''}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {/* ── Metadata badges ── */}
        {!isUser && metadata.confidence !== undefined && (
          <div className="flex flex-wrap items-center gap-2 mt-3 pt-2.5 border-t border-border/40">
            <span className={cn(
              'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium',
              metadata.confidence >= 0.8
                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                : metadata.confidence >= 0.5
                  ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
                  : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
            )}>
              <Shield className="h-3 w-3 flex-shrink-0" />
              {Math.round(metadata.confidence * 100)}% confidence
            </span>
            {metadata.method && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                {metadata.method}
              </span>
            )}
          </div>
        )}

        {/* ── Citations ── */}
        {citations.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setShowCitations(!showCitations)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-accent/50 transition-colors"
            >
              {showCitations ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {citations.length} source{citations.length > 1 ? 's' : ''}
            </button>
            {showCitations && (
              <div className="mt-1.5 space-y-1 animate-fade-in">
                {citations.map((c, i) => (
                  <a
                    key={i}
                    href={c.source}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-xs text-primary hover:underline truncate rounded-md px-1.5 py-1 hover:bg-primary/5 transition-colors"
                  >
                    <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    <span className="truncate">{c.metadata?.title || c.source}</span>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Copy button — bottom right ── */}
        {message.content && !isStreaming && (
          <div className={cn(
            'flex justify-end mt-2 pt-1.5 transition-all duration-200',
            'opacity-0 group-hover:opacity-100',
            (!isUser && metadata.confidence !== undefined) || citations.length > 0
              ? '' : 'border-t border-border/20'
          )}>
            <button
              onClick={handleCopy}
              className={cn(
                'flex items-center gap-1 text-xs px-2 py-1 rounded-md transition-colors',
                copied
                  ? 'text-green-600 dark:text-green-400'
                  : isUser
                    ? 'text-primary-foreground/60 hover:text-primary-foreground hover:bg-white/10'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              )}
              title={copied ? 'Copied!' : 'Copy message'}
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              <span>{copied ? 'Copied!' : 'Copy'}</span>
            </button>
          </div>
        )}
      </div>

      {/* User Avatar */}
      {isUser && (
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center flex-shrink-0 mt-1 shadow-sm">
          <User className="h-4.5 w-4.5 text-primary-foreground" />
        </div>
      )}
    </div>
  );
}
