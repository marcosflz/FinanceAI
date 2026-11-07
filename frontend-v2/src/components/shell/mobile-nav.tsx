"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { mobileNavItems } from "@/components/shell/nav";

export function MobileNav() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      aria-label="Navegación móvil"
    >
      <ul className="grid h-14 grid-cols-5">
        {mobileNavItems.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-full flex-col items-center justify-center gap-1 text-[10px] font-medium transition-colors",
                  active ? "text-accent" : "text-muted-foreground",
                )}
              >
                <Icon
                  className="size-[18px]"
                  strokeWidth={active ? 2.1 : 1.8}
                  aria-hidden
                />
                {item.shortLabel}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
