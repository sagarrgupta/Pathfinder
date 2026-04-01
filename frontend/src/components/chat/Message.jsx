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
  comparison: 'Comparison',
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
  const modePrefix = step.mode_label ? `${step.mode_label}: ` : '';
  return { label, message: `${modePrefix}${step.message || ''}` };
}

export default function Message({ message, isLast, isStreaming }) {
  const [showCitations, setShowCitations] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [copied, setCopied] = useState(false);
  const [expandedComparisonCards, setExpandedComparisonCards] = useState({});
  const [focusedComparisonMode, setFocusedComparisonMode] = useState(null);
  const [comparisonWidths, setComparisonWidths] = useState({});
  const [comparisonHeights, setComparisonHeights] = useState({});
  const isUser = message.role === 'user';
  const metadata = message.metadata || {};
  const citations = metadata.citations || [];
  const progress = message.progress || [];
  const attachments = message.attachments || [];
  const retrievalStats = metadata.retrievalStats || {};
  const comparisonAnswers = metadata.comparisonAnswers || [];
  const comparisonOrder = metadata.comparisonOrder || [];
  const currentCompareMode = metadata.currentCompareMode || null;
  const isComparison = !isUser && metadata.compareMode;
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

  const comparisonCards = (comparisonOrder.length > 0 ? comparisonOrder : comparisonAnswers).map((slot) => {
    const mode = slot.mode || slot;
    const answer = comparisonAnswers.find((item) => item.mode === mode) || null;
    return {
      mode,
      label: slot.label || answer?.label || mode,
      answer,
      status: answer ? 'done' : currentCompareMode === mode ? 'running' : 'waiting',
    };
  });

  const toggleComparisonCard = (mode) => {
    setExpandedComparisonCards((prev) => ({ ...prev, [mode]: !prev[mode] }));
  };

  const toggleFocusedComparisonMode = (mode) => {
    setFocusedComparisonMode((current) => (current === mode ? null : mode));
  };

  const resizeComparisonCardWidth = (mode, delta) => {
    setComparisonWidths((prev) => {
      const next = (prev[mode] ?? 0) + delta;
      return { ...prev, [mode]: Math.max(-2, Math.min(3, next)) };
    });
  };

  const resizeComparisonCardHeight = (mode, delta) => {
    setComparisonHeights((prev) => {
      const next = (prev[mode] ?? 0) + delta;
      return { ...prev, [mode]: Math.max(-1, Math.min(4, next)) };
    });
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
        {isComparison ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Retrieval comparison for this query
              {currentCompareMode && (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Running {comparisonCards.find((card) => card.mode === currentCompareMode)?.label || currentCompareMode}
                </span>
              )}
            </div>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:overflow-x-auto lg:pb-2">
              {comparisonCards.map((card, idx) => (
                <div
                  key={idx}
                  className={cn(
                    'rounded-xl border bg-background/70 p-3 space-y-3 min-h-[26rem] flex flex-col transition-all',
                    focusedComparisonMode === card.mode && 'min-h-[34rem]',
                    focusedComparisonMode && focusedComparisonMode !== card.mode && 'opacity-90'
                  )}
                  style={{
                    width: focusedComparisonMode === card.mode
                      ? 'min(100%, 42rem)'
                      : '100%',
                    minWidth: focusedComparisonMode === card.mode
                      ? 'min(100%, 42rem)'
                      : `min(100%, ${22 + ((comparisonWidths[card.mode] ?? 0) * 5)}rem)`,
                    flexBasis: focusedComparisonMode === card.mode
                      ? '42rem'
                      : `${22 + ((comparisonWidths[card.mode] ?? 0) * 5)}rem`,
                    flexGrow: focusedComparisonMode === card.mode ? 1.35 : 1,
                    flexShrink: 0,
                  }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {card.label}
                      </span>
                      {card.answer ? (
                        <span className={cn(
                          'inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium',
                          card.answer.confidence >= 0.8
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                            : card.answer.confidence >= 0.5
                              ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
                              : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                        )}>
                          <Shield className="h-3 w-3 flex-shrink-0" />
                          {Math.round((card.answer.confidence || 0) * 100)}%
                        </span>
                      ) : (
                        <span className={cn(
                          'inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium',
                          card.status === 'running'
                            ? 'bg-primary/10 text-primary'
                            : 'bg-muted text-muted-foreground'
                        )}>
                          {card.status === 'running' ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                          {card.status === 'running' ? 'Running' : 'Waiting'}
                        </span>
                      )}
                      {card.answer?.retrieval_stats?.elapsed_ms !== undefined && (
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
                          {card.answer.retrieval_stats?.result_count ?? 0} hits • {Math.round(card.answer.retrieval_stats.elapsed_ms)}ms
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <div className="flex items-center gap-1 rounded-md border border-border/60 bg-background/70 p-0.5">
                        <button
                          type="button"
                          onClick={() => resizeComparisonCardWidth(card.mode, -1)}
                          className="text-[11px] rounded px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        >
                          Narrower
                        </button>
                        <button
                          type="button"
                          onClick={() => resizeComparisonCardWidth(card.mode, 1)}
                          className="text-[11px] rounded px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        >
                          Wider
                        </button>
                      </div>
                      <div className="flex items-center gap-1 rounded-md border border-border/60 bg-background/70 p-0.5">
                        <button
                          type="button"
                          onClick={() => resizeComparisonCardHeight(card.mode, -1)}
                          className="text-[11px] rounded px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        >
                          Shorter
                        </button>
                        <button
                          type="button"
                          onClick={() => resizeComparisonCardHeight(card.mode, 1)}
                          className="text-[11px] rounded px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                        >
                          Taller
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={() => toggleFocusedComparisonMode(card.mode)}
                        className={cn(
                          'text-[11px] rounded-md border px-2 py-1 transition-colors',
                          focusedComparisonMode === card.mode
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'border-border/60 text-muted-foreground hover:bg-accent hover:text-foreground'
                        )}
                      >
                        {focusedComparisonMode === card.mode ? 'Unfocus' : 'Focus'}
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleComparisonCard(card.mode)}
                        className="text-[11px] rounded-md border border-border/60 px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        {expandedComparisonCards[card.mode] ? 'Collapse' : 'Expand'}
                      </button>
                    </div>
                  </div>

                  <div className={cn(
                    'rounded-lg border border-border/40 bg-background/60 p-3 overflow-y-auto',
                  )}
                  style={{
                    maxHeight: `${
                      (focusedComparisonMode === card.mode ? 48 : expandedComparisonCards[card.mode] ? 38 : 18)
                      + ((comparisonHeights[card.mode] ?? 0) * 8)
                    }rem`,
                  }}>
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
                        {card.answer?.answer || (card.status === 'running' ? 'Generating answer...' : 'Waiting for this retrieval flow to start...')}
                      </ReactMarkdown>
                    </div>
                  </div>

                  {card.answer?.citations?.length > 0 && (
                    <div className="pt-2 border-t border-border/40 space-y-1 mt-auto">
                      <p className="text-[11px] font-medium text-muted-foreground">Sources</p>
                      {card.answer.citations.slice(0, 4).map((c, citationIdx) => (
                        <a
                          key={citationIdx}
                          href={c.source}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1.5 text-xs text-primary hover:underline truncate rounded-md px-1 py-0.5 hover:bg-primary/5 transition-colors"
                        >
                          <ExternalLink className="h-3 w-3 flex-shrink-0" />
                          <span className="truncate">{c.metadata?.title || c.source}</span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (hasContent || (!isCurrentlyStreaming)) && (
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
        {!isUser && metadata.confidence !== undefined && !isComparison && (
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
            {retrievalStats.elapsed_ms !== undefined && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
                {retrievalStats.result_count ?? 0} hits • {Math.round(retrievalStats.elapsed_ms)}ms
              </span>
            )}
          </div>
        )}

        {/* ── Citations ── */}
        {citations.length > 0 && !isComparison && (
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
