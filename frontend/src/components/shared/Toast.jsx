import React, { useState, useCallback, createContext, useContext } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-react';
import { cn } from '@/lib/utils';

const ToastContext = createContext(null);

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const STYLES = {
  success: 'border border-emerald-200/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(236,253,245,0.94))] text-foreground dark:border-emerald-900/50 dark:bg-[linear-gradient(135deg,rgba(12,18,16,0.96),rgba(5,46,22,0.72))]',
  error: 'border border-red-200/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(254,242,242,0.94))] text-foreground dark:border-red-900/50 dark:bg-[linear-gradient(135deg,rgba(20,12,12,0.96),rgba(69,10,10,0.72))]',
  warning: 'border border-amber-200/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(255,251,235,0.94))] text-foreground dark:border-amber-900/50 dark:bg-[linear-gradient(135deg,rgba(20,16,10,0.96),rgba(120,53,15,0.65))]',
  info: 'border border-border/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(239,246,255,0.92))] text-foreground dark:bg-[linear-gradient(135deg,rgba(12,18,28,0.96),rgba(15,23,42,0.82))]',
};

const ICON_STYLES = {
  success: 'text-green-500 dark:text-green-400',
  error: 'text-red-500 dark:text-red-400',
  warning: 'text-yellow-500 dark:text-yellow-400',
  info: 'text-blue-500 dark:text-blue-400',
};

let toastId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, message, type }]);
    if (duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, duration);
    }
    return id;
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = React.useMemo(() => ({
    success: (msg, dur) => addToast(msg, 'success', dur),
    error: (msg, dur) => addToast(msg, 'error', dur ?? 6000),
    warning: (msg, dur) => addToast(msg, 'warning', dur),
    info: (msg, dur) => addToast(msg, 'info', dur),
  }), [addToast]);

  const value = { toast, addToast, removeToast };

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Toast Container */}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-full max-w-sm flex-col gap-3">
        {toasts.map((t) => {
          const Icon = ICONS[t.type];
          return (
            <div
              key={t.id}
              className={cn(
                'pointer-events-auto flex items-center gap-3 rounded-[22px] px-4 py-3 shadow-[0_22px_55px_rgba(15,23,42,0.14)] animate-fade-in-up backdrop-blur-xl',
                STYLES[t.type]
              )}
            >
              <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-2xl bg-background/65">
                <Icon className={cn('h-4.5 w-4.5', ICON_STYLES[t.type])} />
              </div>
              <p className="flex-1 self-center text-sm leading-relaxed">{t.message}</p>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => removeToast(t.id)}
                className="flex-shrink-0 self-center rounded-md p-1 opacity-60 transition-opacity hover:bg-muted hover:opacity-100"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx.toast;
}
