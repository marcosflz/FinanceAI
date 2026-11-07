"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CornerDownLeft,
  Search,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import { navItems } from "@/components/shell/nav";
import { cn } from "@/lib/utils";

interface CommandItem {
  href: string;
  label: string;
  description: string;
  keywords: string[];
  group: string;
  icon: typeof Search;
}

const actionItems: CommandItem[] = [
  {
    href: "/movements?tab=por-revisar",
    label: "Revisar pendientes",
    description: "Abrir la bandeja de revisión",
    keywords: ["revisar", "pendiente", "cola", "aprobar"],
    group: "Acciones",
    icon: Sparkles,
  },
  {
    href: "/imports",
    label: "Importar extracto",
    description: "CSV, PDF o imagen",
    keywords: ["importar", "subir", "csv", "pdf"],
    group: "Acciones",
    icon: UploadCloud,
  },
];

function buildItems(): CommandItem[] {
  return [
    ...navItems.map((item) => ({
      href: item.href,
      label: item.label,
      description: item.description,
      keywords: item.keywords,
      group: "Ir a",
      icon: item.icon,
    })),
    ...actionItems,
  ];
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const items = useMemo(() => buildItems(), []);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) =>
      [item.label, item.description, ...item.keywords]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [items, query]);

  const close = useCallback(() => setOpen(false), []);
  const openPalette = useCallback(() => {
    setQuery("");
    setActive(0);
    setOpen(true);
  }, []);

  const go = useCallback(
    (item: CommandItem | undefined) => {
      if (!item) return;
      setOpen(false);
      router.push(item.href);
    },
    [router],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (open) close();
        else openPalette();
      }
      if (event.key === "Escape" && open) close();
    }

    function onCommandEvent() {
      openPalette();
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("ft:command", onCommandEvent);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("ft:command", onCommandEvent);
    };
  }, [open, close, openPalette]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[12vh] sm:pt-[16vh]">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-[var(--overlay)] backdrop-blur-[2px]"
        aria-label="Cerrar búsqueda"
        onClick={close}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Comandos y navegación"
        className="animate-dialog-in relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-popover shadow-2xl"
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((value) => Math.min(filtered.length - 1, value + 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((value) => Math.max(0, value - 1));
              }
              if (event.key === "Enter") {
                event.preventDefault();
                go(filtered[active]);
              }
            }}
            placeholder="Buscar pantallas, acciones…"
            aria-label="Buscar pantallas y acciones"
            className="h-12 w-full bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground"
          />
          <kbd className="num hidden rounded border border-border bg-muted px-1.5 py-1 text-[10px] text-muted-foreground sm:block">
            esc
          </kbd>
        </div>

        <div className="max-h-[min(360px,55vh)] overflow-y-auto p-1.5">
          {filtered.length === 0 ? (
            <div className="px-3 py-10 text-center">
              <p className="text-[13px] font-medium">Sin resultados</p>
              <p className="mt-1 text-xs text-muted-foreground">
                La búsqueda global de movimientos llegará con{" "}
                <span className="num">/api/v3/search</span>.
              </p>
            </div>
          ) : (
            <ul>
              {filtered.map((item, index) => {
                const Icon = item.icon;
                const isActive = index === active;
                return (
                  <li key={`${item.group}-${item.href}-${item.label}`}>
                    <button
                      type="button"
                      onMouseEnter={() => setActive(index)}
                      onClick={() => go(item)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors",
                        isActive ? "bg-muted" : "hover:bg-muted/70",
                      )}
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
                        <Icon className="size-3.5" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-foreground">
                          {item.label}
                        </span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {item.description}
                        </span>
                      </span>
                      {isActive ? (
                        <CornerDownLeft className="size-3.5 text-muted-foreground" aria-hidden />
                      ) : (
                        <ArrowRight className="size-3.5 text-transparent" aria-hidden />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-2">
            <span>
              <kbd className="rounded border border-border bg-muted px-1">↑</kbd>{" "}
              <kbd className="rounded border border-border bg-muted px-1">↓</kbd>{" "}
              navegar
            </span>
            <span>
              <kbd className="rounded border border-border bg-muted px-1">↵</kbd> abrir
            </span>
          </span>
          <span>Placeholder F5 · sin búsqueda full-text</span>
        </div>
      </div>
    </div>
  );
}
