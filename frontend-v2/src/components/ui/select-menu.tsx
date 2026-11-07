"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Popover } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
  /** Punto de color delante de la etiqueta (categorías). */
  color?: string;
  /** Texto secundario a la derecha. */
  hint?: string;
  group?: string;
}

export type SelectVariant = "field" | "pill" | "inline";

export interface SelectMenuProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  /** Texto cuando el valor no coincide con ninguna opción. */
  placeholder?: string;
  variant?: SelectVariant;
  /** Resalta el disparador (filtro activo). Solo ``pill``. */
  active?: boolean;
  icon?: ReactNode;
  /** Buscador dentro del menú; por defecto a partir de 8 opciones. */
  searchable?: boolean;
  disabled?: boolean;
  id?: string;
  name?: string;
  title?: string;
  "aria-label"?: string;
  className?: string;
  menuClassName?: string;
  align?: "start" | "end";
}

const triggerVariants: Record<SelectVariant, string> = {
  field:
    "h-9 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground hover:border-muted-foreground/40 focus-visible:border-accent",
  pill: "h-8 shrink-0 rounded-full border px-3 text-[12px] font-medium",
  inline:
    "h-7 w-full min-w-0 rounded-md border border-transparent bg-transparent px-1.5 text-foreground hover:border-border focus-visible:border-accent focus-visible:outline-none",
};

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/** Selector propio: misma estética en todos los navegadores, búsqueda y teclado. */
export const SelectMenu = forwardRef<HTMLButtonElement, SelectMenuProps>(function SelectMenu(
  {
    value,
    onValueChange,
    options,
    placeholder = "Selecciona…",
    variant = "field",
    active = false,
    icon,
    searchable,
    disabled = false,
    id,
    name,
    title,
    "aria-label": ariaLabel,
    className,
    menuClassName,
    align = "start",
  },
  ref,
) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  useImperativeHandle(ref, () => triggerRef.current as HTMLButtonElement);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(-1);
  const typeahead = useRef({ text: "", at: 0 });

  const selected = options.find((option) => option.value === value);
  const showSearch = searchable ?? options.length > 8;

  const filtered = useMemo(() => {
    const needle = normalize(query.trim());
    if (!needle) return options;
    return options.filter((option) =>
      normalize(`${option.label} ${option.hint ?? ""} ${option.group ?? ""}`).includes(needle),
    );
  }, [options, query]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
  }, []);

  function openMenu() {
    if (disabled) return;
    const index = options.findIndex((option) => option.value === value);
    setHighlight(index >= 0 ? index : options.findIndex((option) => !option.disabled));
    setQuery("");
    setOpen(true);
  }

  function choose(option: SelectOption | undefined) {
    if (!option || option.disabled) return;
    if (option.value !== value) onValueChange(option.value);
    close();
    triggerRef.current?.focus();
  }

  function move(delta: 1 | -1) {
    if (filtered.length === 0) return;
    let next = highlight;
    for (let step = 0; step < filtered.length; step += 1) {
      next = (next + delta + filtered.length) % filtered.length;
      if (!filtered[next]?.disabled) break;
    }
    setHighlight(next);
  }

  useEffect(() => {
    if (!open) return;
    if (showSearch) searchRef.current?.focus();
    else listRef.current?.focus();
  }, [open, showSearch]);

  useEffect(() => {
    if (!open || highlight < 0) return;
    // Desplaza solo la lista; ``scrollIntoView`` movería también la página.
    const list = listRef.current;
    const item = list?.querySelector<HTMLElement>(`[data-index="${highlight}"]`);
    if (!list || !item) return;
    const top = item.offsetTop - list.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + item.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + item.offsetHeight - list.clientHeight;
    }
  }, [open, highlight]);

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      openMenu();
    }
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      setHighlight(filtered.findIndex((option) => !option.disabled));
    } else if (event.key === "End") {
      event.preventDefault();
      for (let index = filtered.length - 1; index >= 0; index -= 1) {
        if (!filtered[index].disabled) {
          setHighlight(index);
          break;
        }
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[highlight]);
    } else if (event.key === "Tab") {
      close();
    } else if (!showSearch && event.key.length === 1 && !event.metaKey && !event.ctrlKey) {
      const now = Date.now();
      const buffer = now - typeahead.current.at < 600 ? typeahead.current.text + event.key : event.key;
      typeahead.current = { text: buffer, at: now };
      const needle = normalize(buffer);
      const index = filtered.findIndex(
        (option) => !option.disabled && normalize(option.label).startsWith(needle),
      );
      if (index >= 0) setHighlight(index);
    }
  }

  const triggerTone =
    variant === "pill"
      ? active
        ? "border-accent/40 bg-accent-soft text-accent-soft-foreground"
        : "border-border bg-card text-muted-foreground hover:border-input hover:text-foreground"
      : "";
  const placeholderTone = !selected && variant !== "pill" ? "text-muted-foreground" : "";

  let lastGroup: string | undefined;

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        name={name}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        title={title ?? selected?.label}
        disabled={disabled}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={onTriggerKeyDown}
        className={cn(
          "group inline-flex min-w-0 cursor-pointer select-none items-center gap-1.5 text-left transition-colors",
          "disabled:cursor-not-allowed disabled:opacity-50",
          triggerVariants[variant],
          triggerTone,
          placeholderTone,
          open && variant === "field" && "border-accent",
          className,
        )}
      >
        {icon ? <span className="flex shrink-0 items-center">{icon}</span> : null}
        {selected?.color && !icon ? (
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: selected.color }}
            aria-hidden
          />
        ) : null}
        <span className="min-w-0 flex-1 truncate">{selected?.label ?? placeholder}</span>
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 opacity-60 transition-transform",
            variant === "inline" &&
              "size-3 opacity-0 group-hover:opacity-60 group-focus-visible:opacity-60 group-disabled:hidden",
            open && "rotate-180 opacity-60",
          )}
          aria-hidden
        />
      </button>

      <Popover
        open={open}
        onClose={close}
        anchorRef={triggerRef}
        align={align}
        matchWidth
        role="presentation"
        className={cn("flex min-w-[11rem] max-w-[22rem] flex-col p-1", menuClassName)}
      >
        {showSearch ? (
          <div className="relative mb-1 shrink-0">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setHighlight(0);
              }}
              onKeyDown={onMenuKeyDown}
              placeholder="Buscar…"
              aria-label="Filtrar opciones"
              aria-controls={listboxId}
              aria-activedescendant={highlight >= 0 ? `${listboxId}-${highlight}` : undefined}
              className="h-8 w-full rounded-lg border border-border bg-card pl-8 pr-2 text-[12px] placeholder:text-muted-foreground focus-visible:border-accent focus-visible:outline-none"
            />
          </div>
        ) : null}
        <div
          ref={listRef}
          id={listboxId}
          role="listbox"
          tabIndex={-1}
          aria-label={ariaLabel}
          aria-activedescendant={highlight >= 0 ? `${listboxId}-${highlight}` : undefined}
          onKeyDown={showSearch ? undefined : onMenuKeyDown}
          className="scrollbar-thin min-h-0 flex-1 overflow-y-auto focus-visible:outline-none"
        >
          {filtered.length === 0 ? (
            <p className="px-2.5 py-3 text-center text-[12px] text-muted-foreground">Sin resultados</p>
          ) : (
            filtered.map((option, index) => {
              const isSelected = option.value === value;
              const header =
                option.group && option.group !== lastGroup ? option.group : null;
              lastGroup = option.group;
              return (
                <div key={`${option.group ?? ""}:${option.value}`}>
                  {header ? (
                    <p className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      {header}
                    </p>
                  ) : null}
                  <div
                    id={`${listboxId}-${index}`}
                    data-index={index}
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={option.disabled || undefined}
                    onPointerMove={() => !option.disabled && setHighlight(index)}
                    onClick={() => choose(option)}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-foreground",
                      highlight === index && "bg-muted",
                      option.disabled && "cursor-not-allowed opacity-45",
                    )}
                  >
                    {option.color ? (
                      <span
                        className="size-2 shrink-0 rounded-full"
                        style={{ backgroundColor: option.color }}
                        aria-hidden
                      />
                    ) : null}
                    <span className={cn("min-w-0 flex-1 truncate", isSelected && "font-medium")}>
                      {option.label}
                    </span>
                    {option.hint ? (
                      <span className="shrink-0 text-[11px] text-muted-foreground">{option.hint}</span>
                    ) : null}
                    <Check
                      className={cn("size-3.5 shrink-0 text-accent", !isSelected && "invisible")}
                      aria-hidden
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Popover>
    </>
  );
});
