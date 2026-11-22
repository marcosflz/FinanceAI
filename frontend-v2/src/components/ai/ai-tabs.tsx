"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { aiSections } from "@/components/shell/nav";
import { cn } from "@/lib/utils";

/** Pestañas de la sección IA, a todo el ancho bajo la barra superior. */
export function AiTabs() {
  const pathname = usePathname();
  return (
    <div className="-mx-4 -mt-6 mb-5 border-b border-border bg-background sm:-mx-6 lg:-mx-8 lg:-mt-5">
      <nav
        aria-label="Secciones de IA"
        className="scrollbar-thin flex h-11 items-stretch gap-1 overflow-x-auto px-4 sm:px-6 lg:px-8"
      >
        {aiSections.map((item) => {
          const active = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex shrink-0 items-center gap-1.5 px-2.5 text-[13px] font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className={cn("size-3.5", active && "text-accent")} strokeWidth={1.9} aria-hidden />
              <span className="sm:hidden">{item.shortLabel}</span>
              <span className="hidden sm:inline">{item.label}</span>
              {active ? (
                <span className="absolute inset-x-1.5 -bottom-px h-0.5 rounded-full bg-accent" aria-hidden />
              ) : null}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
