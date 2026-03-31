import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '@/context/AppContext';
import { getSavedRecommendations } from '@/services/api';
import { CheckSquare, Loader2, Calendar, ArrowRight, Sparkles, Clock3 } from 'lucide-react';

export default function PlansPage() {
  const { state, dispatch } = useApp();
  const navigate = useNavigate();
  const studentId = state.activeStudentId;
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!studentId) return;
    (async () => {
      setLoading(true);
      try {
        const items = await getSavedRecommendations(studentId);
        dispatch({ type: 'SET_SAVED_RECOMMENDATIONS', payload: items });
      } finally {
        setLoading(false);
      }
    })();
  }, [studentId, dispatch]);

  const items = state.savedRecommendations || [];
  const stats = useMemo(() => ({
    active: items.filter((item) => (item.status || '').toLowerCase() !== 'done').length,
    needsReview: items.filter((item) => item.next_review_at).length,
    followUps: items.filter((item) => item.follow_up_prompt).length,
  }), [items]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Loading saved plans…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-fade">
      <div className="mx-auto max-w-4xl space-y-6 p-6 animate-fade-in">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/10">
            <CheckSquare className="h-7 w-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Saved Plans</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Recommendations and action plans Pathfinder saved for this profile.
            </p>
          </div>
        </div>

        {items.length === 0 ? (
          <div className="rounded-2xl border bg-card p-10 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/8 text-primary">
              <CheckSquare className="h-5 w-5" />
            </div>
            <h2 className="text-lg font-semibold tracking-tight">No saved plans yet</h2>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
              This space fills up after Pathfinder turns a recommendation into next steps you can revisit later.
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                onClick={() => navigate('/chat')}
                className="inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
              >
                Start a guided chat
              </button>
              <button
                type="button"
                onClick={() => navigate('/profile')}
                className="inline-flex items-center rounded-lg border px-4 py-2 text-sm font-medium transition-colors hover:bg-accent"
              >
                Complete profile
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <PlanMetric label="Active plans" value={stats.active} />
              <PlanMetric label="Need review" value={stats.needsReview} />
              <PlanMetric label="Follow-ups" value={stats.followUps} />
            </div>

            {items.map((item) => (
              <div key={item.id} className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-semibold tracking-tight">{item.title}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">{item.summary}</p>
                  </div>
                  <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                    {item.recommendation_type}
                  </span>
                </div>

                {item.actions?.length > 0 && (
                  <div className="rounded-xl bg-muted/35 px-4 py-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                      Action Steps
                    </p>
                    <div className="space-y-2">
                      {item.actions.map((action, index) => (
                        <div key={index} className="flex items-start gap-2 text-sm">
                          <ArrowRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                          <span>{action}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {item.created_at && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/40 px-2.5 py-1">
                      <Calendar className="h-3 w-3" />
                      {new Date(item.created_at).toLocaleString()}
                    </span>
                  )}
                  {item.source_query && (
                    <span className="truncate rounded-full bg-muted/40 px-2.5 py-1">From: {item.source_query}</span>
                  )}
                  {item.status && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/40 px-2.5 py-1">
                      <Sparkles className="h-3 w-3" />
                      {item.status}
                    </span>
                  )}
                  {item.next_review_at && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/40 px-2.5 py-1">
                      <Clock3 className="h-3 w-3" />
                      Review by {new Date(item.next_review_at).toLocaleDateString()}
                    </span>
                  )}
                </div>

                {item.follow_up_prompt && (
                  <div className="rounded-xl border border-primary/10 bg-primary/5 px-4 py-3">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-primary/80">
                      Follow-up Prompt
                    </p>
                    <p className="text-sm">{item.follow_up_prompt}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PlanMetric({ label, value }) {
  return (
    <div className="rounded-2xl border bg-card px-4 py-4 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  );
}
