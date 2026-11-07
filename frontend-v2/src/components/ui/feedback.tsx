import type { ReactNode } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3", index === lines - 1 ? "w-3/5" : "w-full")}
        />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" aria-label="Cargando datos" role="status">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="grid grid-cols-12 items-center gap-4 py-2">
          <Skeleton className="col-span-2 h-3" />
          <Skeleton className="col-span-4 h-3" />
          <Skeleton className="col-span-2 h-3" />
          <Skeleton className="col-span-2 h-3" />
          <Skeleton className="col-span-2 h-3" />
        </div>
      ))}
    </div>
  );
}

export function CardsSkeleton({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 xl:grid-cols-4", className)}>
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="card p-5" aria-hidden>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-4 h-7 w-36" />
          <Skeleton className="mt-3 h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Cargando página">
      <div className="space-y-2">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-3 w-80" />
      </div>
      <CardsSkeleton />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2 p-5">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="mt-5 h-64 w-full" />
        </div>
        <div className="card p-5">
          <Skeleton className="h-3 w-32" />
          <div className="mt-5 space-y-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-14 text-center",
        className,
      )}
    >
      <div className="mb-3 flex size-10 items-center justify-center rounded-xl border border-border bg-muted text-muted-foreground">
        {icon ?? <Inbox className="size-4" aria-hidden />}
      </div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = "No se pudieron cargar los datos",
  description = "Comprueba que el backend está disponible e inténtalo de nuevo.",
  action,
  className,
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("card flex flex-col items-center px-6 py-12 text-center", className)}>
      <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-negative-soft text-negative">
        <AlertTriangle className="size-4" aria-hidden />
      </div>
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 max-w-md text-xs text-muted-foreground">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function Progress({
  value,
  className,
  tone = "accent",
  label,
}: {
  value: number;
  className?: string;
  tone?: "accent" | "positive" | "negative" | "warning";
  label?: string;
}) {
  const tones = {
    accent: "bg-accent",
    positive: "bg-positive",
    negative: "bg-negative",
    warning: "bg-warning",
  } as const;
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", tones[tone])}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
