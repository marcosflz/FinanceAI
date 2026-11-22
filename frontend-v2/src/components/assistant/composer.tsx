"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ArrowUp, Loader2, Square, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Composer al estilo Nexus: tarjeta redondeada con textarea que crece y una
 * barra inferior (herramientas a la izquierda, modelo y enviar a la derecha).
 */
export function Composer({
  onSend,
  onStop,
  busy,
  disabled,
  placeholder,
  left,
  right,
  chips,
  autoFocus,
  className,
}: {
  onSend: (text: string) => void;
  /** Si se indica, mientras ``busy`` el botón detiene la respuesta. */
  onStop?: () => void;
  busy?: boolean;
  disabled?: boolean;
  placeholder?: string;
  left?: ReactNode;
  right?: ReactNode;
  chips?: { label: string; onRemove: () => void }[];
  autoFocus?: boolean;
  className?: string;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || busy || disabled) return;
    onSend(text);
    setValue("");
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className={cn(
        "rounded-2xl border border-border bg-card shadow-1 transition-[border-color,box-shadow] duration-150",
        "focus-within:border-border-strong focus-within:shadow-2",
        className,
      )}
    >
      {chips?.length ? (
        <div className="flex flex-wrap gap-1.5 px-3 pt-3">
          {chips.map((chip) => (
            <span
              key={chip.label}
              className="inline-flex items-center gap-1 rounded-full bg-accent-soft py-0.5 pl-2.5 pr-1 font-mono text-[12px] text-accent-soft-foreground"
            >
              {chip.label}
              <button
                type="button"
                onClick={chip.onRemove}
                aria-label={`Quitar ${chip.label}`}
                className="rounded-full p-0.5 hover:bg-accent/10"
              >
                <X className="size-3" aria-hidden />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <textarea
        ref={ref}
        aria-label="Mensaje"
        rows={1}
        value={value}
        autoFocus={autoFocus}
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        className="block max-h-60 min-h-[56px] w-full resize-none bg-transparent px-4 pt-4 text-[16px] leading-6 outline-none placeholder:text-muted-foreground focus-visible:outline-none disabled:opacity-60 sm:text-[15px]"
      />
      <div className="flex items-center gap-1 px-2 pb-2 pt-1">
        <div className="flex min-w-0 items-center gap-1">{left}</div>
        <div className="ml-auto flex min-w-0 items-center gap-1.5">
          {right}
          {busy && onStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Detener"
              title="Detener"
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90"
            >
              <Square className="size-3.5 fill-current" aria-hidden />
            </button>
          ) : (
            <button
              type="submit"
              disabled={busy || disabled || !value.trim()}
              aria-label={busy ? "Generando" : "Enviar"}
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-30"
            >
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <ArrowUp className="size-4" aria-hidden />}
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
