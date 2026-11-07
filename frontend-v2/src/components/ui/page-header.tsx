import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-[22px] font-semibold leading-7 tracking-[-0.02em] text-foreground">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 max-w-2xl text-[13px] leading-5 text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">{actions}</div>
      ) : null}
    </header>
  );
}

export interface LinkTabItem {
  value: string;
  label: string;
  href: string;
  count?: number;
}

export function LinkTabs({
  items,
  active,
  className,
}: {
  items: LinkTabItem[];
  active: string;
  className?: string;
}) {
  return (
    <nav
      className={cn(
        "scrollbar-thin flex items-center gap-1 overflow-x-auto border-b border-border",
        className,
      )}
      aria-label="Vistas"
    >
      {items.map((item) => {
        const isActive = item.value === active;
        return (
          <Link
            key={item.value}
            href={item.href}
            scroll={false}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "relative flex h-10 shrink-0 items-center gap-1.5 px-2.5 text-[13px] font-medium transition-colors",
              isActive
                ? "text-foreground after:absolute after:inset-x-1.5 after:bottom-0 after:h-[2px] after:rounded-full after:bg-accent"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            {typeof item.count === "number" ? (
              <span
                className={cn(
                  "num rounded px-1 text-[10px] font-medium",
                  isActive
                    ? "bg-accent-soft text-accent-soft-foreground"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {item.count}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

export function SectionCardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-3.5">
      <div>
        <h2 className="text-[13px] font-semibold text-foreground">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
