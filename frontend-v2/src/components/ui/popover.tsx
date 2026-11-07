"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

// Fija desde el primer render: si no, ``focus``/``scrollIntoView`` dentro de la
// capa desplazarían la página antes de colocarla.
const HIDDEN: CSSProperties = { position: "fixed", top: 0, left: 0, opacity: 0 };

/**
 * Capa flotante anclada a un elemento. Se monta en ``document.body`` con
 * posición fija, así no la recortan tablas ni contenedores con ``overflow``.
 * Se coloca debajo del ancla y se da la vuelta si no cabe; se cierra al
 * pulsar fuera o con Escape.
 */
export function Popover({
  open,
  onClose,
  anchorRef,
  children,
  align = "start",
  matchWidth = false,
  className,
  role = "dialog",
  ariaLabel,
  id,
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLElement | null>;
  children: ReactNode;
  align?: "start" | "end";
  matchWidth?: boolean;
  className?: string;
  role?: string;
  ariaLabel?: string;
  id?: string;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>(HIDDEN);

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    const content = contentRef.current;
    if (!anchor || !content) return;
    const rect = anchor.getBoundingClientRect();
    const margin = 8;
    const gap = 6;
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const width = Math.min(
      Math.max(content.offsetWidth, matchWidth ? rect.width : 0),
      viewportW - margin * 2,
    );
    const height = content.offsetHeight;

    let left = align === "end" ? rect.right - width : rect.left;
    left = Math.max(margin, Math.min(left, viewportW - width - margin));

    const below = viewportH - rect.bottom - gap - margin;
    const above = rect.top - gap - margin;
    const placeAbove = height > below && above > below;
    const maxHeight = Math.max(160, placeAbove ? above : below);
    const top = placeAbove
      ? Math.max(margin, rect.top - gap - Math.min(height, maxHeight))
      : rect.bottom + gap;

    setStyle({
      position: "fixed",
      top,
      left,
      minWidth: matchWidth ? rect.width : undefined,
      maxWidth: viewportW - margin * 2,
      maxHeight,
      opacity: 1,
    });
  }, [align, anchorRef, matchWidth]);

  useLayoutEffect(() => {
    if (!open) return;
    place();
  }, [open, place, children]);

  useEffect(() => {
    if (!open) return;
    const content = contentRef.current;
    const observer =
      typeof ResizeObserver !== "undefined" && content
        ? new ResizeObserver(() => place())
        : null;
    if (observer && content) observer.observe(content);

    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (contentRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        anchorRef.current?.focus();
      }
    }
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open, onClose, place, anchorRef]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={contentRef}
      id={id}
      role={role}
      aria-label={ariaLabel}
      style={style}
      className={cn(
        "animate-fade-in z-[90] overflow-auto rounded-xl border border-border bg-popover text-popover-foreground shadow-lg",
        className,
      )}
    >
      {children}
    </div>,
    document.body,
  );
}
