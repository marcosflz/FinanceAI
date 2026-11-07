import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant =
  | "neutral"
  | "accent"
  | "positive"
  | "negative"
  | "warning"
  | "outline"
  | "info";

const variants: Record<Variant, string> = {
  neutral: "border-transparent bg-muted text-muted-foreground",
  accent: "border-transparent bg-accent-soft text-accent-soft-foreground",
  positive: "border-transparent bg-positive-soft text-positive",
  negative: "border-transparent bg-negative-soft text-negative",
  warning: "border-transparent bg-warning-soft text-warning",
  outline: "border-border bg-transparent text-muted-foreground",
  info: "border-transparent bg-info-soft text-info",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant;
  dot?: boolean;
}

export function Badge({ className, variant = "neutral", dot, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded-md border px-1.5 text-[11px] font-medium leading-none",
        variants[variant],
        className,
      )}
      {...props}
    >
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}
