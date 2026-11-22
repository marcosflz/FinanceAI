import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Texto con brillo animado para estados «trabajando…» (portado de Nexus). */
export function TextShimmer({
  as = "span",
  className,
  duration = 4,
  spread = 20,
  children,
  ...props
}: {
  as?: ElementType;
  duration?: number;
  spread?: number;
  children: ReactNode;
} & HTMLAttributes<HTMLElement>) {
  const width = Math.min(Math.max(spread, 5), 45);
  const Component = as;
  return (
    <Component
      className={cn(
        "bg-size-[200%_auto] bg-clip-text font-medium text-transparent",
        "animate-[shimmer_4s_infinite_linear]",
        className,
      )}
      style={{
        backgroundImage: `linear-gradient(to right, var(--muted-foreground) ${50 - width}%, var(--foreground) 50%, var(--muted-foreground) ${50 + width}%)`,
        animationDuration: `${duration}s`,
      }}
      {...props}
    >
      {children}
    </Component>
  );
}
