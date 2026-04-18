import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  User, Sparkles, ChevronDown, ChevronUp, ExternalLink,
  Copy, Check, Loader2, CheckCircle2, Paperclip, Wrench,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const STEP_LABELS = {
  input_guard: 'Input Guard',
  orchestrator: 'Routing',
  specialist_runner: 'Specialist',
  response_validator: 'Validation',
  responder: 'Response',
  doc_analyst: 'Documents',
};

function formatStep(step) {
  const label = STEP_LABELS[step.node] || step.node;
  return { label, message: step.message || '' };
}

function formatPriority(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeCitation(citation, index) {
  const url = citation?.url || citation?.source || '';
  const title = citation?.title || citation?.metadata?.title || `Source ${index + 1}`;
  const tool = citation?.tool || '';
  return { url, title, tool };
}

function summarizeToolCalls(toolCalls) {
  const counts = new Map();
  toolCalls.forEach((item) => {
    const name = String(item?.tool || '').trim();
    if (!name) return;
    counts.set(name, (counts.get(name) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([tool, count]) => ({ tool, count }))
    .sort((a, b) => b.count - a.count || a.tool.localeCompare(b.tool));
}

function DiagnosticSection({ title, children }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-background/75 p-3 shadow-sm">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground">
        {title}
      </p>
      {children}
    </div>
  );
}

export default function Message({ message, isLast, isStreaming }) {
  const [showCitations, setShowCitations] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [showSystemContext, setShowSystemContext] = useState(false);
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const metadata = message.metadata || {};
  const citations = (metadata.citations || []).map(normalizeCitation);
  const progress = message.progress || [];
  const attachments = message.attachments || [];
  const trimmedContent = String(message.content || '').trim();
  const isCurrentlyStreaming = isLast && isStreaming && !isUser;
  const hasContent = !!message.content;
  const runtimeSnapshot = metadata.runtimeSnapshot || {};
  const dependencyStatus = metadata.dependencyStatus || {};
  const replayId = metadata.replayId || '';
  const selectedSpecialist = metadata.selectedSpecialist || '';
  const routingScores = metadata.routingScores || {};
  const routingReason = metadata.routingReason || '';
  const toolCallLog = Array.isArray(metadata.toolCallLog) ? metadata.toolCallLog : [];
  const documentIngestion = metadata.documentIngestion || {};
  const ingestionDocuments = Array.isArray(documentIngestion.documents)
    ? documentIngestion.documents
    : [];
  const ingestionToolCalls = ingestionDocuments.flatMap((item) =>
    Array.isArray(item?.ingestion_result?.tool_call_log) ? item.ingestion_result.tool_call_log : []
  );
  const combinedToolCallLog = [...toolCallLog, ...ingestionToolCalls];
  const specialistOutput = metadata.specialistOutput || {};
  const successfulToolCalls = combinedToolCallLog.filter((item) => item?.status === 'ok');
  const toolUsage = summarizeToolCalls(successfulToolCalls);
  const methodLabel = metadata.method && metadata.method !== 'direct' ? metadata.method : '';
  const qualityPathLabel = metadata.qualityPath && metadata.qualityPath !== 'direct' ? metadata.qualityPath : '';
  const hasMeaningfulRouting = Object.values(routingScores).some((value) => Number(value) > 0);
  const hasRuntimeWarnings = Object.values(dependencyStatus).some(
    (status) => status !== 'connected' && status !== 'configured'
  );
  const isShortUserPill = isUser
    && attachments.length === 0
    && trimmedContent.length > 0
    && trimmedContent.length <= 24
    && !trimmedContent.includes('\n');
  const systemContextAvailable = !isUser && (
    (selectedSpecialist && hasMeaningfulRouting) ||
    (routingReason && hasMeaningfulRouting) ||
    successfulToolCalls.length > 0 ||
    hasRuntimeWarnings ||
    (runtimeSnapshot.selected_retrieval_mode && methodLabel) ||
    (runtimeSnapshot.selected_text_model && successfulToolCalls.length > 0) ||
    (replayId && (successfulToolCalls.length > 0 || hasMeaningfulRouting))
  );

  const buildCopyText = () => {
    const parts = [];
    if (message.content) {
      parts.push(message.content.trim());
    }
    if (citations.length > 0) {
      const sourcesText = citations
        .map((c, i) => `${i + 1}. ${c.title}${c.url ? `\n${c.url}` : ''}`)
        .join('\n\n');
      parts.push(`Sources:\n${sourcesText}`);
    }
    return parts.filter(Boolean).join('\n\n').trim();
  };

  const handleCopy = async () => {
    const copyText = buildCopyText();
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = copyText;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const bubbleWrapperClass = isUser
    ? 'flex max-w-[42rem] flex-col items-end'
    : 'flex w-full max-w-[56rem] flex-col items-start';

  const bubbleClass = isUser
    ? cn(
        'border border-primary/18 bg-gradient-to-br from-primary to-primary/90 text-primary-foreground shadow-sm transition-colors',
        isShortUserPill
          ? 'inline-flex min-w-[3.6rem] items-center justify-center self-end rounded-full px-4 py-2.5'
          : 'rounded-[22px] px-4 py-3'
      )
    : 'w-full rounded-[22px] border border-border/70 bg-background/76 px-4 py-3 shadow-sm backdrop-blur-sm transition-colors';

  return (
    <div
      className={cn(
        'flex items-start gap-3',
        isUser ? 'justify-end' : 'justify-start',
        message.content && !isStreaming && 'mb-12'
      )}
    >
      {!isUser && (
        <div className="mt-1 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl border border-border/60 bg-background/70 shadow-sm">
          <Sparkles className="h-4 w-4 text-primary" />
        </div>
      )}

      <div className={cn('group relative', bubbleWrapperClass)}>
        <div className={bubbleClass}>
        {!isUser && progress.length > 0 && (
          <div className="mb-3">
            {isCurrentlyStreaming && !hasContent ? (
              <div className="space-y-1.5">
                {progress.map((step, i) => {
                  const { label, message: stepMessage } = formatStep(step);
                  return (
                    <div key={i} className={cn('flex items-center gap-2 text-xs', i === progress.length - 1 ? 'animate-fade-in' : '')}>
                      {i === progress.length - 1 ? (
                        <Loader2 className="h-3 w-3 animate-spin text-primary flex-shrink-0" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3 text-green-500 dark:text-green-400 flex-shrink-0" />
                      )}
                      <span className="font-medium text-foreground/70">{label}</span>
                      <span className="text-muted-foreground">{stepMessage}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
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
                      const { label, message: stepMessage } = formatStep(step);
                      return (
                        <div key={i} className="flex items-center gap-2 text-xs pl-2">
                          <CheckCircle2 className="h-3 w-3 text-green-500 dark:text-green-400 flex-shrink-0" />
                          <span className="font-medium text-foreground/70">{label}</span>
                          <span className="text-muted-foreground">{stepMessage}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {isUser && attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {attachments.map((file, i) => (
              <div key={i} className="inline-flex items-center gap-1.5 rounded-full bg-white/14 px-2.5 py-1 text-xs font-medium">
                <Paperclip className="h-3 w-3 flex-shrink-0 opacity-70" />
                <span className="truncate max-w-[160px]">{file.name}</span>
              </div>
            ))}
          </div>
        )}

        {(hasContent || !isCurrentlyStreaming) && (
          <div className={cn('max-w-none', isCurrentlyStreaming ? 'animate-pulse' : '')}>
            {isUser ? (
              <p className={cn(
                'm-0 whitespace-pre-wrap text-[15px]',
                isShortUserPill ? 'text-center leading-6' : 'leading-7'
              )}>
                {message.content}
              </p>
            ) : (
              <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-p:my-2 prose-p:leading-7 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-table:my-3 prose-table:text-sm prose-th:px-3 prose-th:py-1.5 prose-th:bg-muted/50 prose-th:font-medium prose-th:text-left prose-td:px-3 prose-td:py-1.5 prose-td:border-t prose-strong:font-semibold prose-code:text-xs prose-code:bg-muted/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:font-mono prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-blockquote:border-primary/30 prose-blockquote:text-muted-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content || ''}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {!isUser && (selectedSpecialist || methodLabel || qualityPathLabel || routingReason) && (
          <div className="mt-3 border-t border-border/40 pt-2.5">
            <div className="flex flex-wrap items-center gap-2">
              {selectedSpecialist && (
                <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary">
                  {formatPriority(selectedSpecialist)}
                </span>
              )}
              {methodLabel && (
                <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
                  {methodLabel}
                </span>
              )}
              {qualityPathLabel && (
                <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
                  {qualityPathLabel}
                </span>
              )}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {successfulToolCalls.length > 0 && (
                <span>
                  Used {successfulToolCalls.length} call{successfulToolCalls.length === 1 ? '' : 's'}
                  {toolUsage.length > 0 ? ` across ${toolUsage.length} tool${toolUsage.length === 1 ? '' : 's'}` : ''}
                </span>
              )}
              {citations.length > 0 && (
                <span>{citations.length} source{citations.length === 1 ? '' : 's'}</span>
              )}
            </div>

            {routingReason && hasMeaningfulRouting && (
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {routingReason}
              </p>
            )}
          </div>
        )}

        {!isUser && systemContextAvailable && (
          <div className="mt-2">
            <button
              onClick={() => setShowSystemContext(!showSystemContext)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-accent/50 transition-colors"
            >
              {showSystemContext ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              Why this answer
            </button>
            {showSystemContext && (
              <div className="mt-2 space-y-3 rounded-[20px] border border-border/70 bg-card/75 p-3.5 shadow-sm animate-fade-in">
                {selectedSpecialist && hasMeaningfulRouting && (
                  <DiagnosticSection title="Handled By">
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary font-semibold">
                        {formatPriority(selectedSpecialist)}
                      </span>
                    </div>
                  </DiagnosticSection>
                )}

                {hasMeaningfulRouting && (
                  <DiagnosticSection title="Routing Signals">
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(routingScores)
                        .sort((a, b) => Number(b[1]) - Number(a[1]))
                        .map(([name, score]) => (
                          <span key={name} className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                            {formatPriority(name)} {Number(score).toFixed(1)}
                          </span>
                        ))}
                    </div>
                  </DiagnosticSection>
                )}

                {(specialistOutput?.stop_reason || successfulToolCalls.length > 0) && (
                  <DiagnosticSection title="Tools Used">
                    <div className="flex flex-wrap gap-1.5">
                      {toolUsage.map((item) => (
                        <span key={item.tool} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-primary/10 text-primary">
                          <Wrench className="h-3 w-3" />
                          {item.tool}: {item.count}
                        </span>
                      ))}
                      {specialistOutput?.stop_reason && (
                        <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                          Stop: {specialistOutput.stop_reason}
                        </span>
                      )}
                    </div>
                  </DiagnosticSection>
                )}

                {(hasRuntimeWarnings || (runtimeSnapshot.selected_retrieval_mode && methodLabel) || (runtimeSnapshot.selected_text_model && successfulToolCalls.length > 0)) && (
                  <DiagnosticSection title="Runtime Details">
                    <div className="flex flex-wrap gap-1.5">
                      {runtimeSnapshot.reasoning && (
                        <span className="text-xs px-2 py-1 rounded-full bg-primary/10 text-primary font-medium">
                          Reasoning: {formatPriority(runtimeSnapshot.reasoning)}
                        </span>
                      )}
                      {runtimeSnapshot.selected_text_model && (
                        <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                          {runtimeSnapshot.selected_text_model}
                        </span>
                      )}
                      {runtimeSnapshot.selected_retrieval_mode && methodLabel && (
                        <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                          {runtimeSnapshot.selected_retrieval_mode}
                        </span>
                      )}
                      {Object.entries(dependencyStatus).map(([name, status]) => (
                        <span
                          key={name}
                          className={cn(
                            'text-xs px-2 py-1 rounded-full font-medium',
                            status === 'connected' || status === 'configured'
                              ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                              : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                          )}
                        >
                          {name}: {status}
                        </span>
                      ))}
                    </div>
                  </DiagnosticSection>
                )}

                {replayId && (successfulToolCalls.length > 0 || hasMeaningfulRouting) && (
                  <DiagnosticSection title="Saved Replay">
                    <a
                      href={`/replays?replay=${encodeURIComponent(replayId)}`}
                      className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/15"
                    >
                      Open {replayId}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </DiagnosticSection>
                )}
              </div>
            )}
          </div>
        )}

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
              <div className="mt-2 space-y-2 animate-fade-in">
                {citations.map((citation, i) => (
                  <a
                    key={`${citation.url || citation.title}-${i}`}
                    href={citation.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-2 rounded-2xl border border-border/60 bg-card/70 px-3 py-2 text-xs transition-colors hover:border-primary/20 hover:bg-primary/5"
                  >
                    <div className="mt-0.5 rounded-full bg-primary/10 p-1 text-primary">
                      <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    </div>
                    <div className="min-w-0">
                      <p className="truncate font-medium text-foreground">{citation.title}</p>
                      <p className="truncate text-muted-foreground">
                        {citation.tool ? `via ${citation.tool}` : citation.url}
                      </p>
                    </div>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}
        </div>

        {message.content && !isStreaming && (
          <div className={cn(
            'pointer-events-none absolute z-10 transition-all duration-200',
            isUser ? 'right-0 top-full' : 'left-0 top-full',
            'opacity-0 translate-y-1 group-hover:opacity-100 group-hover:translate-y-0'
          )}>
            <button
              onClick={handleCopy}
              className={cn(
                'pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full border shadow-sm backdrop-blur-sm transition-all hover:scale-105',
                copied
                  ? 'border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400'
                  : isUser
                    ? 'border-white/20 bg-slate-950/45 text-white shadow-[0_10px_24px_rgba(2,8,23,0.28)] hover:bg-slate-900/60 hover:text-white'
                    : 'border-border/60 bg-background/92 text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
              style={{
                transform: 'translateY(0.5rem)',
              }}
              title={copied ? 'Copied!' : 'Copy message'}
              aria-label={copied ? 'Copied' : 'Copy message'}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center flex-shrink-0 mt-1 shadow-sm">
          <User className="h-4.5 w-4.5 text-primary-foreground" />
        </div>
      )}
    </div>
  );
}
