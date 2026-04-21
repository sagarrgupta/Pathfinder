import React from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';

export default function StreamingProgress({ steps }) {
  return (
    <div className="border-t border-border/50 bg-card/55 px-4 py-3 backdrop-blur-xl">
      <div className="mx-auto max-w-3xl space-y-2">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-2 rounded-xl border border-border/60 bg-background/60 px-3 py-2 text-xs text-muted-foreground shadow-sm">
            {i === steps.length - 1 ? (
              <Loader2 className="h-3 w-3 animate-spin text-primary" />
            ) : (
              <CheckCircle2 className="h-3 w-3 text-green-500" />
            )}
            <span className="font-medium text-foreground/70">{step.node}:</span>
            <span>{step.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
