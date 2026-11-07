"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** ``danger`` para acciones destructivas (borrar, vaciar…). */
  tone?: "default" | "danger";
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

/** ``const confirm = useConfirm(); if (!(await confirm({...}))) return;`` */
export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error("useConfirm debe usarse dentro de ConfirmProvider");
  return context;
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        returnFocus.current = document.activeElement as HTMLElement | null;
        setPending((current) => {
          current?.resolve(false);
          return { ...options, resolve };
        });
      }),
    [],
  );

  const settle = useCallback((value: boolean) => {
    setPending((current) => {
      current?.resolve(value);
      return null;
    });
    returnFocus.current?.focus?.();
  }, []);

  useEffect(() => {
    if (!pending) return;
    // En acciones destructivas el foco inicial va a "Cancelar".
    (pending.tone === "danger" ? cancelRef : confirmRef).current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        settle(false);
      } else if (event.key === "Tab") {
        const focusables = dialogRef.current?.querySelectorAll<HTMLElement>("button");
        if (!focusables || focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [pending, settle]);

  const danger = pending?.tone === "danger";
  const Icon = danger ? AlertTriangle : HelpCircle;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && typeof document !== "undefined"
        ? createPortal(
            <div className="fixed inset-0 z-[85] flex items-end justify-center p-3 sm:items-center sm:p-6">
              <div
                className="animate-fade-in absolute inset-0 bg-[var(--overlay)] backdrop-blur-[2px]"
                onClick={() => settle(false)}
                aria-hidden
              />
              <div
                ref={dialogRef}
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="confirm-dialog-title"
                aria-describedby={pending.description ? "confirm-dialog-description" : undefined}
                className="animate-dialog-in relative w-full max-w-md rounded-2xl border border-border bg-popover p-5 shadow-2xl"
              >
                <div className="flex gap-3.5">
                  <span
                    className={cn(
                      "flex size-9 shrink-0 items-center justify-center rounded-full",
                      danger ? "bg-negative-soft text-negative" : "bg-accent-soft text-accent-soft-foreground",
                    )}
                    aria-hidden
                  >
                    <Icon className="size-4" />
                  </span>
                  <div className="min-w-0 pt-1">
                    <h2 id="confirm-dialog-title" className="text-[15px] font-semibold text-foreground">
                      {pending.title}
                    </h2>
                    {pending.description ? (
                      <div
                        id="confirm-dialog-description"
                        className="mt-1.5 text-[13px] leading-5 text-muted-foreground"
                      >
                        {pending.description}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <Button ref={cancelRef} variant="secondary" onClick={() => settle(false)}>
                    {pending.cancelLabel ?? "Cancelar"}
                  </Button>
                  <Button
                    ref={confirmRef}
                    variant={danger ? "danger" : "primary"}
                    onClick={() => settle(true)}
                  >
                    {pending.confirmLabel ?? "Confirmar"}
                  </Button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </ConfirmContext.Provider>
  );
}
