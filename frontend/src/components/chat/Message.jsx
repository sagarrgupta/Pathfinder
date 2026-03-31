import React, { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  User, Sparkles, ChevronDown, ChevronUp, ExternalLink,
  Shield, Copy, Check, Loader2, CheckCircle2, Paperclip,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// Map technical node names to user-friendly phase labels
const STEP_LABELS = {
  guardrail_agent: 'Guardrails',
  question_triage: 'Triage',
  reasoning_planner: 'Planner',
  profile_memory_agent: 'Profile Memory',
  semantic_memory_agent: 'Semantic Memory',
  document_evidence_agent: 'Document Evidence',
  web_researcher: 'Research',
  evidence_judge_agent: 'Evidence Judge',
  conflict_resolution_agent: 'Conflict Check',
  missing_info_agent: 'Missing Info',
  academic_strategy_agent: 'Academic Strategy',
  career_strategy_agent: 'Career Strategy',
  interview_coach_agent: 'Interview Coach',
  decision_comparison_agent: 'Decision Support',
  document_understanding_agent: 'Document Insight',
  plan_action_agent: 'Action Plan',
  answer_composer_agent: 'Answer Composer',
  memory_writer_agent: 'Memory Writer',
  memory_consolidation_agent: 'Memory Consolidation',
};

function formatStep(step) {
  const label = STEP_LABELS[step.node] || step.node;
  return { label, message: step.message || '' };
}

export default function Message({ message, isLast, isStreaming, onConflictAction }) {
  const [showCitations, setShowCitations] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selectedConflictAction, setSelectedConflictAction] = useState('');
  const [conflictActionState, setConflictActionState] = useState({ loading: false, done: false, message: '', error: '' });
  const isUser = message.role === 'user';
  const metadata = message.metadata || {};
  const citations = metadata.citations || [];
  const progress = message.progress || [];
  const attachments = message.attachments || [];
  const rationale = metadata.rationale || [];
  const sources = metadata.sources || [];
  const recommendedActions = metadata.recommendedActions || [];
  const conflictNudges = metadata.conflictNudges || [];
  const missingInfo = metadata.missingInfo || [];
  const retrievalSummary = metadata.retrievalSummary || {};
  const executionTrace = metadata.executionTrace || [];
  const isCurrentlyStreaming = isLast && isStreaming && !isUser;
  const hasContent = !!message.content;
  const compactContextSummary = `${retrievalSummary.candidate_facts || 0} facts • ${retrievalSummary.documents || 0} docs • ${retrievalSummary.web_results || 0} web`;
  const hasDetails = Boolean(
    metadata.confidence !== undefined
      || sources.length > 0
      || rationale.length > 0
      || missingInfo.length > 0
      || retrievalSummary.documents
      || retrievalSummary.web_results
      || retrievalSummary.candidate_facts
      || executionTrace.length > 0
  );
  const primaryConflictNudge = conflictNudges[0] || null;
  const conflictOptions = useMemo(() => {
    if (!primaryConflictNudge) return [];
    if (primaryConflictNudge.options?.length) return primaryConflictNudge.options;
    const value = primaryConflictNudge.value || '';
    const alternatives = primaryConflictNudge.alternatives || [];
    return [
      ...(value ? [{ action: 'choose_value', value, label: `Use '${value}' as current` }] : []),
      ...alternatives.filter(Boolean).map((alt) => ({ action: 'choose_value', value: alt, label: `Use '${alt}' as current` })),
      { action: 'keep_both', label: 'Keep both for now' },
      { action: 'ask_later', label: 'Ask me later' },
    ];
  }, [primaryConflictNudge]);

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

  const handleConflictApply = async () => {
    if (!primaryConflictNudge || !selectedConflictAction || !onConflictAction) return;
    const [action, ...valueParts] = selectedConflictAction.split('::');
    const selectedValue = valueParts.join('::') || undefined;
    setConflictActionState({ loading: true, done: false, message: '', error: '' });
    try {
      const result = await onConflictAction({
        conflict_id: primaryConflictNudge.id,
        fact_type: primaryConflictNudge.fact_type,
        action,
        selected_value: selectedValue,
      });
      setConflictActionState({
        loading: false,
        done: true,
        message: result?.message || 'Saved your choice.',
        error: '',
      });
    } catch (error) {
      setConflictActionState({
        loading: false,
        done: false,
        message: '',
        error: error?.message || 'Could not save your choice.',
      });
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
        'group rounded-2xl px-4 py-3 shadow-sm transition-colors',
        isUser
          ? 'max-w-[75%] bg-primary text-primary-foreground'
          : 'max-w-[min(100%,820px)] border border-border/60 bg-muted/55'
      )}>
        {/* ── Collapsible Progress (bot only) ── */}
        {!isUser && progress.length > 0 && (
          <div className="mb-3">
            {/* During streaming: show live progress */}
            {isCurrentlyStreaming && !hasContent ? (
              (() => {
                const latest = progress[progress.length - 1];
                const { label, message } = formatStep(latest);
                return (
                  <div className="flex items-center gap-2 text-xs animate-fade-in rounded-lg bg-background/60 px-2.5 py-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary flex-shrink-0" />
                    <span className="font-medium text-foreground/80">{label}</span>
                    <span className="text-muted-foreground truncate">{message}</span>
                  </div>
                );
              })()
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

        {!isUser && conflictNudges.length > 0 && (
          <div className="mt-3 rounded-lg border border-amber-200/60 bg-amber-50/80 dark:border-amber-800/50 dark:bg-amber-950/30 px-3 py-2">
            <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-1">Profile uncertainty</p>
            {primaryConflictNudge && (
              <>
                <p className="text-xs text-amber-900/80 dark:text-amber-200/80">{primaryConflictNudge.message}</p>
                {primaryConflictNudge.summary?.question && (
                  <div className="mt-2 rounded-md bg-amber-100/70 px-2.5 py-2 text-xs text-amber-950 dark:bg-amber-900/30 dark:text-amber-100">
                    <p className="font-medium">{primaryConflictNudge.summary.question}</p>
                    <div className="mt-1 space-y-0.5 text-amber-900/80 dark:text-amber-200/85">
                      {primaryConflictNudge.summary.current_option && (
                        <p>Current option: {primaryConflictNudge.summary.current_option}</p>
                      )}
                      {primaryConflictNudge.summary.other_options?.length > 0 && (
                        <p>Other option{primaryConflictNudge.summary.other_options.length > 1 ? 's' : ''}: {primaryConflictNudge.summary.other_options.join(', ')}</p>
                      )}
                    </div>
                  </div>
                )}
                {!conflictActionState.done && conflictOptions.length > 0 && (
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                    <select
                      value={selectedConflictAction}
                      onChange={(e) => setSelectedConflictAction(e.target.value)}
                      className="h-8 rounded-md border border-amber-200 bg-background px-2 text-xs text-foreground dark:border-amber-800 dark:bg-background"
                    >
                      <option value="">Choose what to do</option>
                      {conflictOptions.map((option) => (
                        <option
                          key={`${option.action}-${option.value || option.label}`}
                          value={option.value ? `${option.action}::${option.value}` : option.action}
                        >
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={handleConflictApply}
                      disabled={!selectedConflictAction || conflictActionState.loading}
                      className="inline-flex h-8 items-center justify-center rounded-md bg-amber-600 px-3 text-xs font-medium text-white transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {conflictActionState.loading ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Apply'}
                    </button>
                  </div>
                )}
                {conflictActionState.message && (
                  <p className="mt-2 text-xs text-amber-900/80 dark:text-amber-200/80">{conflictActionState.message}</p>
                )}
                {conflictActionState.error && (
                  <p className="mt-2 text-xs text-red-700 dark:text-red-300">{conflictActionState.error}</p>
                )}
              </>
            )}
          </div>
        )}

        {!isUser && missingInfo.length > 0 && (
          <div className="mt-2 text-xs text-muted-foreground">
            Most useful extra info: {missingInfo.slice(0, 2).join(', ')}
          </div>
        )}

        {!isUser && recommendedActions.length > 0 && (
          <div className="mt-3 rounded-xl border bg-background/75 px-3 py-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-foreground/75">Suggested next steps</p>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              {recommendedActions.slice(0, 3).map((item, index) => (
                <li key={index} className="flex gap-2">
                  <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary/60" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!isUser && hasDetails && (
          <div className="mt-3">
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-accent/50"
            >
              {showDetails ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              <span>Answer details</span>
            </button>
            {showDetails && (
              <div className="mt-2 space-y-3 rounded-xl border bg-background/70 px-3 py-3 animate-fade-in">
                {metadata.confidence !== undefined && (
                  <div className="flex flex-wrap items-center gap-2">
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
                    {sources.length > 0 && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
                        {sources.slice(0, 2).join(' + ')}
                      </span>
                    )}
                  </div>
                )}

                {(retrievalSummary.documents || retrievalSummary.web_results || retrievalSummary.candidate_facts) && (
                  <div className="inline-flex items-center rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                    Context used: {compactContextSummary}
                  </div>
                )}

                {rationale.length > 0 && (
                  <div className="space-y-1 text-xs text-muted-foreground">
                    {rationale.slice(0, 2).map((item, index) => (
                      <p key={index}>{item}</p>
                    ))}
                  </div>
                )}

                {missingInfo.length > 0 && (
                  <div className="text-xs text-muted-foreground">
                    Most useful extra info: {missingInfo.slice(0, 2).join(', ')}
                  </div>
                )}

                {executionTrace.length > 0 && (
                  <div className="text-[11px] text-muted-foreground">
                    Runtime trace: {executionTrace.map((item) => item.agent).join(' -> ')}
                  </div>
                )}
              </div>
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
