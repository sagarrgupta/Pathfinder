import React from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';

export default function StreamingProgress({ steps }) {
  return (
    <div className="border-t bg-muted/50 px-4 py-2">
      <div className="max-w-3xl mx-auto space-y-1">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
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
