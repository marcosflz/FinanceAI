"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { notificationsApi } from "@/lib/agent-api";
import { DEMO_MODE } from "@/lib/demo";
import { formatDateTime } from "@/lib/utils";
import { Popover } from "@/components/ui/popover";

/** Avisos de automatizaciones (resultados y aprobaciones pendientes). */
export function NotificationsBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["agent", "notifications"],
    queryFn: () => notificationsApi.list(),
    refetchInterval: 60_000,
    enabled: !DEMO_MODE,
  });
  const markRead = useMutation({
    mutationFn: () => notificationsApi.markRead(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "notifications"] }),
  });
  const unread = query.data?.unread ?? 0;
  const items = query.data?.items ?? [];

  const anchorRef = useRef<HTMLButtonElement | null>(null);

  function close() {
    setOpen(false);
    if (unread) markRead.mutate();
  }

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        className="relative inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label={unread ? `Notificaciones (${unread} sin leer)` : "Notificaciones"}
        aria-expanded={open}
      >
        <Bell className="size-4" aria-hidden />
        {unread ? (
          <span className="num absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold text-accent-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </button>
      <Popover open={open} onClose={close} anchorRef={anchorRef} align="end" ariaLabel="Avisos">
        <div className="w-72">
          <p className="border-b border-border px-3 py-2 text-[12px] font-medium">Avisos</p>
          <div className="max-h-80 divide-y divide-border overflow-y-auto">
            {items.length ? (
              items.map((item) => (
                <Link
                  key={item.id}
                  href={item.thread_id ? `/ai/assistant?thread=${item.thread_id}` : "/ai/automations"}
                  onClick={close}
                  className="block px-3 py-2 hover:bg-muted"
                >
                  <p className={`text-[12px] ${item.read ? "text-muted-foreground" : "font-medium"}`}>{item.title}</p>
                  {item.body ? <p className="line-clamp-2 text-[11px] text-muted-foreground">{item.body}</p> : null}
                  <p className="text-[10px] text-muted-foreground">{formatDateTime(`${item.created_at}Z`)}</p>
                </Link>
              ))
            ) : (
              <p className="px-3 py-3 text-[11px] text-muted-foreground">Sin avisos todavía.</p>
            )}
          </div>
        </div>
      </Popover>
    </>
  );
}
