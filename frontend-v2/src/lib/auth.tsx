"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AUTH_UNAUTHORIZED_EVENT, authApi, isUnauthorized } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import { mockUser } from "@/lib/mock";
import type { User } from "@/lib/types";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Button } from "@/components/ui/button";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  error: unknown;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: async (): Promise<User> => (DEMO_MODE ? mockUser : authApi.me()),
    retry: false,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return context;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const query = useMe();

  const redirectToLogin = useCallback(() => {
    queryClient.clear();
    const next =
      pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`/login${next}`);
  }, [pathname, queryClient, router]);

  useEffect(() => {
    if (isUnauthorized(query.error)) redirectToLogin();
  }, [query.error, redirectToLogin]);

  useEffect(() => {
    const handler = () => redirectToLogin();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handler);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handler);
  }, [redirectToLogin]);

  const logout = useCallback(async () => {
    try {
      if (!DEMO_MODE) await authApi.logout();
    } catch {
      // The local session must be cleared even if the server is unreachable.
    } finally {
      if (DEMO_MODE && typeof document !== "undefined") {
        document.cookie = "ft_session=; Max-Age=0; path=/";
      }
      queryClient.clear();
      router.replace("/login");
      router.refresh();
    }
  }, [queryClient, router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: query.data ?? null,
      isLoading: query.isLoading,
      error: query.error,
      logout,
    }),
    [query.data, query.isLoading, query.error, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, isLoading, error } = useAuth();

  if (isLoading) return <PageSkeleton />;

  if (!user) {
    const unauthorized = isUnauthorized(error);
    return (
      <ErrorState
        title={unauthorized ? "Tu sesión ha caducado" : "No se pudo verificar la sesión"}
        description={
          unauthorized
            ? "Te estamos redirigiendo al acceso. Si no ocurre, pulsa el botón."
            : "Comprueba que el backend está disponible e inténtalo de nuevo."
        }
        action={
          <Button variant="primary" onClick={() => window.location.assign("/login")}>
            Ir al acceso
          </Button>
        }
      />
    );
  }

  return children;
}
