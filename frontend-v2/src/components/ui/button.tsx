import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type Size = "sm" | "md" | "icon";

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-foreground hover:bg-accent/90 active:bg-accent/80 border border-transparent",
  secondary:
    "bg-card text-foreground border border-border hover:bg-muted active:bg-muted/80",
  ghost: "bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground border border-transparent",
  danger:
    "bg-negative text-white hover:bg-negative/90 active:bg-negative/80 border border-transparent dark:text-background",
  outline:
    "bg-transparent text-foreground border border-border hover:bg-muted active:bg-muted/80",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  icon: "h-8 w-8 p-0",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "secondary",
      size = "md",
      loading = false,
      disabled,
      children,
      ...props
    },
    ref,
  ) => (
    <button
      ref={ref}
      type={props.type ?? "button"}
      disabled={disabled || loading}
      className={cn(
        "inline-flex select-none items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors duration-150",
        "disabled:pointer-events-none disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  ),
);

Button.displayName = "Button";
