import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  User, Sparkles, ChevronDown, ChevronUp, ExternalLink,
  Shield, Copy, Check, Loader2, CheckCircle2, Paperclip, Wrench,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const STEP_LABELS = {
  input_guard: 'Input Guard',
  orchestrator: 'Routing',
  specialist_runner: 'Specialist',
  light_validator: 'Validation',
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

function confidenceTone(value) {
  const score = Number(value) || 0;
  if (score >= 0.8) return 'High confidence';
  if (score >= 0.5) return 'Moderate confidence';
  return 'Low confidence';
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
  const isCurrentlyStreaming = isLast && isStreaming && !isUser;
  const hasContent = !!message.content;
  const runtimeSnapshot = metadata.runtimeSnapshot || {};
  const dependencyStatus = metadata.dependencyStatus || {};
  const replayId = metadata.replayId || '';
  const selectedSpecialist = metadata.selectedSpecialist || '';
  const routingScores = metadata.routingScores || {};
  const routingReason = metadata.routingReason || '';
  const toolCallLog = Array.isArray(metadata.toolCallLog) ? metadata.toolCallLog : [];
  const specialistOutput = metadata.specialistOutput || {};
  const transcriptStates = Array.isArray(metadata.transcriptStates) ? metadata.transcriptStates : [];
  const successfulToolCalls = toolCallLog.filter((item) => item?.status === 'ok');
  const topTools = successfulToolCalls.slice(0, 4);
  const methodLabel = metadata.method && metadata.method !== 'direct' ? metadata.method : '';
  const qualityPathLabel = metadata.qualityPath && metadata.qualityPath !== 'direct' ? metadata.qualityPath : '';
  const hasMeaningfulRouting = Object.values(routingScores).some((value) => Number(value) > 0);
  const hasRuntimeWarnings = Object.values(dependencyStatus).some(
    (status) => status !== 'connected' && status !== 'configured'
  );
  const systemContextAvailable = !isUser && (
    (selectedSpecialist && hasMeaningfulRouting) ||
    (routingReason && hasMeaningfulRouting) ||
    successfulToolCalls.length > 0 ||
    transcriptStates.length > 0 ||
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

  return (
    <div className={cn('flex gap-3', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser && (
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center flex-shrink-0 mt-1 ring-1 ring-primary/10">
          <Sparkles className="h-4.5 w-4.5 text-primary" />
        </div>
      )}

      <div className={cn(
        'group rounded-2xl px-4 py-3 transition-colors',
        isUser ? 'max-w-[75%] bg-primary text-primary-foreground' : 'max-w-full bg-muted/70'
      )}>
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
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((file, i) => (
              <div key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/15 text-xs font-medium">
                <Paperclip className="h-3 w-3 flex-shrink-0 opacity-70" />
                <span className="truncate max-w-[160px]">{file.name}</span>
              </div>
            ))}
          </div>
        )}

        {(hasContent || !isCurrentlyStreaming) && (
          <div className={cn('max-w-none', isCurrentlyStreaming ? 'animate-pulse' : '')}>
            {isUser ? (
              <p className="whitespace-pre-wrap leading-relaxed m-0">{message.content}</p>
            ) : (
              <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:mt-3 prose-headings:mb-2 prose-headings:font-semibold prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-p:my-1.5 prose-p:leading-relaxed prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-table:my-2 prose-table:text-sm prose-th:px-3 prose-th:py-1.5 prose-th:bg-muted/50 prose-th:font-medium prose-th:text-left prose-td:px-3 prose-td:py-1.5 prose-td:border-t prose-strong:font-semibold prose-code:text-xs prose-code:bg-muted/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:font-mono prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-blockquote:border-primary/30 prose-blockquote:text-muted-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content || ''}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {!isUser && metadata.confidence !== undefined && (
          <div className="mt-3 pt-2.5 border-t border-border/40">
            <div className="flex flex-wrap items-center gap-2">
              {selectedSpecialist && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary font-semibold">
                  {formatPriority(selectedSpecialist)}
                </span>
              )}
              <span className={cn(
                'inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium',
                metadata.confidence >= 0.8
                  ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                  : metadata.confidence >= 0.5
                    ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
                    : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
              )}>
                <Shield className="h-3 w-3 flex-shrink-0" />
                {confidenceTone(metadata.confidence)}
              </span>
              {methodLabel && (
                <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground font-medium">
                  {methodLabel}
                </span>
              )}
              {qualityPathLabel && (
                <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground font-medium">
                  {qualityPathLabel}
                </span>
              )}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{Math.round(metadata.confidence * 100)}% confidence</span>
              {topTools.length > 0 && (
                <span>Used {topTools.length} tool{topTools.length === 1 ? '' : 's'}</span>
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
              <div className="mt-2 rounded-xl border bg-card/60 p-3 space-y-3 animate-fade-in">
                {selectedSpecialist && hasMeaningfulRouting && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Handled By</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary font-semibold">
                        {formatPriority(selectedSpecialist)}
                      </span>
                    </div>
                  </div>
                )}

                {hasMeaningfulRouting && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Routing Signals</p>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(routingScores)
                        .sort((a, b) => Number(b[1]) - Number(a[1]))
                        .map(([name, score]) => (
                          <span key={name} className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                            {formatPriority(name)} {Number(score).toFixed(1)}
                          </span>
                        ))}
                    </div>
                  </div>
                )}

                {(specialistOutput?.stop_reason || successfulToolCalls.length > 0) && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Tools Used</p>
                    <div className="flex flex-wrap gap-1.5">
                      {successfulToolCalls.slice(0, 8).map((item, index) => (
                        <span key={`${item.tool}-${index}`} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-primary/10 text-primary">
                          <Wrench className="h-3 w-3" />
                          {item.tool}
                        </span>
                      ))}
                      {specialistOutput?.stop_reason && (
                        <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                          Stop: {specialistOutput.stop_reason}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {transcriptStates.length > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Document Signals</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                        {transcriptStates.length} transcript state{transcriptStates.length === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>
                )}

                {(hasRuntimeWarnings || (runtimeSnapshot.selected_retrieval_mode && methodLabel) || (runtimeSnapshot.selected_text_model && successfulToolCalls.length > 0)) && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Runtime Details</p>
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
                  </div>
                )}

                {replayId && (successfulToolCalls.length > 0 || hasMeaningfulRouting) && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Saved Replay</p>
                    <a
                      href={`/replays?replay=${encodeURIComponent(replayId)}`}
                      className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-full bg-primary/10 text-primary font-medium hover:bg-primary/15 transition-colors"
                    >
                      Open {replayId}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
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
              <div className="mt-1.5 space-y-1 animate-fade-in">
                {citations.map((citation, i) => (
                  <a
                    key={`${citation.url || citation.title}-${i}`}
                    href={citation.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-xs text-primary hover:underline truncate rounded-md px-1.5 py-1 hover:bg-primary/5 transition-colors"
                  >
                    <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    <span className="truncate">
                      {citation.title}
                      {citation.tool ? ` via ${citation.tool}` : ''}
                    </span>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {message.content && !isStreaming && (
          <div className={cn(
            'flex justify-end mt-2 pt-1.5 transition-all duration-200',
            'opacity-0 group-hover:opacity-100',
            (!isUser && metadata.confidence !== undefined) || citations.length > 0 ? '' : 'border-t border-border/20'
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

      {isUser && (
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center flex-shrink-0 mt-1 shadow-sm">
          <User className="h-4.5 w-4.5 text-primary-foreground" />
        </div>
      )}
    </div>
  );
}
