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

function formatPriority(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function Message({ message, isLast, isStreaming }) {
  const [showCitations, setShowCitations] = useState(false);
  const [showProgress, setShowProgress] = useState(false);
  const [showAdvisorContext, setShowAdvisorContext] = useState(false);
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const metadata = message.metadata || {};
  const citations = metadata.citations || [];
  const progress = message.progress || [];
  const attachments = message.attachments || [];
  const isCurrentlyStreaming = isLast && isStreaming && !isUser;
  const hasContent = !!message.content;
  const studentStrategy = metadata.studentStrategy || {};
  const studentOperatingModel = metadata.studentOperatingModel || {};
  const recommendationOutcomeProfile = metadata.recommendationOutcomeProfile || {};
  const decisionContinuity = metadata.decisionContinuity || {};
  const sessionMemory = metadata.sessionMemory || {};
  const retrievalSummary = metadata.retrievalSummary || {};
  const retrievalTrace = metadata.retrievalTrace || [];
  const retrievalDiagnostics = metadata.retrievalDiagnostics || {};
  const runtimeSnapshot = metadata.runtimeSnapshot || {};
  const dependencyStatus = metadata.dependencyStatus || {};
  const replayId = metadata.replayId || '';
  const advisorContextAvailable = !isUser && (
    studentStrategy.primary_priority ||
    studentOperatingModel.risk_tolerance ||
    recommendationOutcomeProfile.follow_through_style ||
    decisionContinuity.is_continuation ||
    sessionMemory.transcript_digest?.kept_turns ||
    retrievalSummary.strategy ||
    retrievalDiagnostics.evidence_quality?.overall_quality ||
    retrievalTrace.length > 0 ||
    runtimeSnapshot.selected_retrieval_mode ||
    Object.keys(dependencyStatus).length > 0 ||
    replayId
  );

  const buildCopyText = () => {
    const parts = [];

    if (message.content) {
      parts.push(message.content.trim());
    }

    if (citations.length > 0) {
      const sourcesText = citations
        .map((c, i) => {
          const title = c.metadata?.title || `Source ${i + 1}`;
          return `${i + 1}. ${title}\n${c.source}`;
        })
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
            {metadata.qualityPath && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
                {metadata.qualityPath}
              </span>
            )}
          </div>
        )}

        {!isUser && advisorContextAvailable && (
          <div className="mt-2">
            <button
              onClick={() => setShowAdvisorContext(!showAdvisorContext)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-accent/50 transition-colors"
            >
              {showAdvisorContext ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              Advisor context
            </button>
            {showAdvisorContext && (
              <div className="mt-2 rounded-xl border bg-card/60 p-3 space-y-3 animate-fade-in">
                {studentStrategy.primary_priority && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Student Strategy</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {formatPriority(studentStrategy.primary_priority)}
                      </span>
                      {(studentStrategy.priorities || []).slice(1, 4).map((priority) => (
                        <span key={priority} className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {formatPriority(priority)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {studentOperatingModel.risk_tolerance && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Operating Model</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {formatPriority(studentOperatingModel.risk_tolerance)} risk
                      </span>
                      {studentOperatingModel.workload_preference && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {formatPriority(studentOperatingModel.workload_preference)} load
                        </span>
                      )}
                      {studentOperatingModel.internship_urgency && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Internship urgency: {formatPriority(studentOperatingModel.internship_urgency)}
                        </span>
                      )}
                      {studentOperatingModel.certainty_preference && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Certainty: {formatPriority(studentOperatingModel.certainty_preference)}
                        </span>
                      )}
                      {studentOperatingModel.grad_school_seriousness && studentOperatingModel.grad_school_seriousness !== 'low' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Grad school: {formatPriority(studentOperatingModel.grad_school_seriousness)}
                        </span>
                      )}
                      {studentOperatingModel.planning_style && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {formatPriority(studentOperatingModel.planning_style)}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {recommendationOutcomeProfile.follow_through_style && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Recommendation History</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {formatPriority(recommendationOutcomeProfile.follow_through_style)}
                      </span>
                      {Array.isArray(recommendationOutcomeProfile.preferred_recommendation_types) &&
                        recommendationOutcomeProfile.preferred_recommendation_types.slice(0, 3).map((item) => (
                          <span key={item} className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                            Prefers {formatPriority(item)}
                          </span>
                        ))}
                      {typeof recommendationOutcomeProfile.follow_through_ratio === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Follow-through {(recommendationOutcomeProfile.follow_through_ratio * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {decisionContinuity.is_continuation && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Decision Continuity</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        Continuing prior plan
                      </span>
                      {decisionContinuity.latest_title && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {decisionContinuity.latest_title}
                        </span>
                      )}
                      {typeof decisionContinuity.related_count === 'number' && decisionContinuity.related_count > 1 && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {decisionContinuity.related_count} related decisions
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {sessionMemory.transcript_digest?.kept_turns > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Session Memory</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                        {sessionMemory.transcript_digest.kept_turns} turns kept
                      </span>
                      {sessionMemory.transcript_digest?.omitted_turns > 0 && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {sessionMemory.transcript_digest.omitted_turns} compacted
                        </span>
                      )}
                      {sessionMemory.lifecycle?.ttl_seconds > 0 && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          TTL {Math.round(sessionMemory.lifecycle.ttl_seconds / 3600)}h
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {(retrievalSummary.strategy || retrievalTrace.length > 0) && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Evidence Path</p>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {retrievalSummary.strategy && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                          {retrievalSummary.strategy}
                        </span>
                      )}
                      {typeof retrievalSummary.document_count === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {retrievalSummary.document_count} docs
                        </span>
                      )}
                      {typeof retrievalSummary.web_count === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {retrievalSummary.web_count} web
                        </span>
                      )}
                      {typeof retrievalSummary.evidence_record_count === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {retrievalSummary.evidence_record_count} facts
                        </span>
                      )}
                    </div>
                    {retrievalTrace.length > 0 && (
                      <div className="space-y-1.5">
                        {retrievalTrace.slice(0, 3).map((item, index) => (
                          <div key={`${item.source}-${item.label}-${index}`} className="text-xs rounded-lg border bg-muted/30 px-2.5 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-foreground truncate">{item.label}</span>
                              <span className="text-muted-foreground">{item.source}</span>
                            </div>
                            {item.reason?.matched_terms?.length > 0 && (
                              <p className="text-muted-foreground mt-1">
                                matched: {item.reason.matched_terms.slice(0, 4).join(', ')}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {retrievalDiagnostics.evidence_quality?.overall_quality > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Evidence Quality</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        Overall {(retrievalDiagnostics.evidence_quality.overall_quality * 100).toFixed(0)}%
                      </span>
                      {typeof retrievalDiagnostics.evidence_quality.document_trust_avg === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Docs {(retrievalDiagnostics.evidence_quality.document_trust_avg * 100).toFixed(0)}%
                        </span>
                      )}
                      {typeof retrievalDiagnostics.evidence_quality.web_quality_avg === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          Web {(retrievalDiagnostics.evidence_quality.web_quality_avg * 100).toFixed(0)}%
                        </span>
                      )}
                      {typeof retrievalDiagnostics.evidence_quality.official_web_hits === 'number' && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {retrievalDiagnostics.evidence_quality.official_web_hits} official web
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {(runtimeSnapshot.selected_text_model || runtimeSnapshot.selected_retrieval_mode || Object.keys(dependencyStatus).length > 0) && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Runtime</p>
                    <div className="flex flex-wrap gap-1.5">
                      {runtimeSnapshot.advisor_mode && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                          {formatPriority(runtimeSnapshot.advisor_mode)}
                        </span>
                      )}
                      {runtimeSnapshot.selected_text_model && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {runtimeSnapshot.selected_text_model}
                        </span>
                      )}
                      {runtimeSnapshot.selected_retrieval_mode && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                          {runtimeSnapshot.selected_retrieval_mode}
                        </span>
                      )}
                      {Object.entries(dependencyStatus).map(([name, status]) => (
                        <span
                          key={name}
                          className={cn(
                            'text-xs px-2 py-0.5 rounded-full font-medium',
                            status === 'connected'
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

                {replayId && (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Replay</p>
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
