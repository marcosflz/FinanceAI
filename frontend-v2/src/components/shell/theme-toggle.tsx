"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { resolved, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={resolved === "dark" ? "Activar tema claro" : "Activar tema oscuro"}
      title={resolved === "dark" ? "Tema claro" : "Tema oscuro"}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        className,
      )}
    >
      <Sun className={cn("size-4", resolved === "dark" && "hidden")} aria-hidden />
      <Moon className={cn("size-4", resolved !== "dark" && "hidden")} aria-hidden />
    </button>
  );
}
