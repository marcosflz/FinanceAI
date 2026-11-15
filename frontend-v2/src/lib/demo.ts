import { ApiError, isApiUnavailable } from "@/lib/api";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Fallback a datos de ejemplo solo en desarrollo local. En producción un 404
// o un 502 (backend reiniciando) debe mostrarse como error: antes se pintaban
// saldos y movimientos ficticios como si fueran reales.
const DEV_FALLBACK = process.env.NODE_ENV === "development";

/**
 * Reads from the real API. In demo mode returns the fixture; in local
 * development keeps the scaffold usable when the backend is not running.
 * Authentication and validation errors are never masked.
 */
export async function withMock<T>(
  request: () => Promise<T>,
  fallback: T,
  options: { delay?: number } = {},
): Promise<T> {
  if (DEMO_MODE) {
    await sleep(options.delay ?? 180);
    return fallback;
  }

  try {
    return await request();
  } catch (error) {
    if (
      DEV_FALLBACK &&
      isApiUnavailable(error) &&
      !(error instanceof ApiError && error.status === 401)
    ) {
      await sleep(options.delay ?? 120);
      return fallback;
    }
    throw error;
  }
}
