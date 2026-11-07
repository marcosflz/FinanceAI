"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, CheckCircle2, Info, Undo2, X } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastVariant = "default" | "success" | "error";

interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastInput {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
  action?: ToastAction;
}

interface ToastItem extends ToastInput {
  id: string;
}

interface ToastContextValue {
  toast: (input: ToastInput) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast debe usarse dentro de ToastProvider");
  return context;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;
      setItems((current) => [...current.slice(-3), { ...input, id }]);
      const duration = input.duration ?? (input.action ? 7000 : 4500);
      if (duration > 0) {
        const timer = setTimeout(() => dismiss(id), duration);
        timers.current.set(id, timer);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-20 z-[80] flex flex-col items-center gap-2 px-4 sm:bottom-6 sm:left-auto sm:right-6 sm:items-end sm:px-0"
        aria-live="polite"
        aria-atomic="false"
      >
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              "animate-fade-in pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-lg",
            )}
            role="status"
          >
            <span className="mt-0.5 shrink-0">
              {item.variant === "success" ? (
                <CheckCircle2 className="size-4 text-positive" aria-hidden />
              ) : item.variant === "error" ? (
                <AlertTriangle className="size-4 text-negative" aria-hidden />
              ) : (
                <Info className="size-4 text-accent" aria-hidden />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium leading-4">{item.title}</p>
              {item.description ? (
                <p className="mt-1 text-xs leading-4 text-muted-foreground">
                  {item.description}
                </p>
              ) : null}
              {item.action ? (
                <button
                  type="button"
                  onClick={() => {
                    item.action?.onClick();
                    dismiss(item.id);
                  }}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <Undo2 className="size-3" aria-hidden />
                  {item.action.label}
                </button>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              aria-label="Cerrar aviso"
              className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
