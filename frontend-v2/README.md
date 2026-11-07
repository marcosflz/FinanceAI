# Financial Tools — frontend v2 (scaffold F5)

Frontend nuevo del plan de auditoría 2026-10-31. Vive en `frontend-v2/` y **no
modifica ni sustituye** el frontend actual de `frontend/`; la idea es revisarlo,
validarlo y cambiar la carpeta cuando el backend v3 esté listo.

- **Stack:** Next.js 16.1.6 (App Router) · React 19.2.3 · TypeScript · Tailwind 4 ·
  TanStack Query 5 · lucide-react · Recharts 3.
- **Estado:** scaffold visual + contratos API. Las pantallas funcionan con mocks
  deterministas cuando la API v3 no responde. Auth, mutaciones de movimientos,
  importación y cuentas ya llaman a los endpoints previstos.
- **Sin secretos:** no hay claves, URLs de producción ni credenciales en el código.

## Arranque

```bash
cd frontend-v2
npm install
cp .env.example .env.local       # opcional
npm run dev                      # http://localhost:3000
```

Con backend real en `http://localhost:8001`:

```bash
BACKEND_URL=http://localhost:8001 npm run dev
```

Para revisar todas las pantallas sin backend (login demo + mocks):

```bash
NEXT_PUBLIC_DEMO_MODE=true npm run dev
```

En ese modo `/login` muestra **Entrar en modo demo** y escribe una cookie
`ft_session=demo` solo para que el middleware deje pasar. No concede acceso a la
API real y **nunca debe activarse en producción**.

Si quieres previsualizar un `next build`/`next start` en modo demo, la variable
se inlinea en build:

```bash
NEXT_PUBLIC_DEMO_MODE=true npm run build
NEXT_PUBLIC_DEMO_MODE=true npm run start
```

Calidad:

```bash
npm run typecheck
npm run lint
npm run build
```

Resultado local: `npm install` correcto, `tsc --noEmit` sin errores, `eslint` sin
errores ni warnings y `next build` correcto (10 rutas). Next 16 avisa de que
`middleware.ts` está deprecado en favor de `proxy.ts`; se mantiene
`middleware.ts` porque es el contrato pedido por F5. Migrar a `proxy.ts` es una
tarea mecánica para F7.

## Variables de entorno

| Variable | Uso | Defecto |
|---|---|---|
| `BACKEND_URL` | Origen del backend para el rewrite server-side `/api/:path*` | `http://localhost:8001` |
| `NEXT_PUBLIC_API_URL` | Base opcional para llamadas directas desde el navegador | vacío = same-origin + rewrite |
| `NEXT_PUBLIC_DEMO_MODE` | Activa login demo y datos mock | `false` |

Recomendación: dejar `NEXT_PUBLIC_API_URL` vacío. Así las cookies de sesión y CSRF
quedan first-party y el navegador solo habla con el mismo origen.

## Autenticación y API

- `POST /api/v3/auth/login` `{ email, password, remember }`.
- `POST /api/v3/auth/logout`, `GET /api/v3/auth/me`,
  `POST /api/v3/auth/change-password`.
- El cliente envía `credentials: "include"` en todas las llamadas.
- Para `POST/PATCH/DELETE` lee la cookie `ft_csrf` (o `__Host-ft_csrf`) y añade
  `X-CSRF-Token`. Si el backend usa otro nombre, se ajusta en
  `src/lib/api.ts`.
- Cualquier `401` dispara `ft:unauthorized`: se limpia la caché de TanStack Query
  y se redirige a `/login?next=...`.
- `src/middleware.ts` comprueba **solo la presencia** de `ft_session` o
  `__Host-ft_session` y redirige a `/login`; la API valida la sesión de verdad.
  `/login` queda fuera del redirect para evitar bucles con cookies caducadas.

Contrato asumido para los endpoints (ajustable cuando aterrice el backend v3):

| Recurso | Respuesta esperada |
|---|---|
| `GET /api/v3/movements` | `{ items: Movement[], total, page, page_size, next_cursor, summary? }` |
| `PATCH /api/v3/movements/{id}` | `Movement` actualizado |
| `POST /api/v3/movements/bulk` | `{ updated: number }` |
| `GET /api/v3/imports` | `{ items: ImportSummary[], total, next_cursor }` |
| `GET /api/v3/imports/{id}` | `ImportDetail` con `transactions`, `incidences`, `raw_rows`, `reconciliation` |
| `POST /api/v3/imports` | multipart, campo `files` (una o varias veces) |
| `GET /api/v3/accounts` | `{ items: Account[] }` |
| `GET /api/v3/transfers/suggestions` | `{ items: TransferSuggestion[] }` |
| `GET /api/v3/dedup-candidates` | `{ items: DedupCandidate[] }` |
| `GET /api/v3/analytics/summary` | `AnalyticsSummary` |
| `GET /api/v3/analytics/cashflow?months=12` | `{ items: CashflowPoint[] }` |
| `GET /api/v3/analytics/by-category` | `{ items: CategoryBreakdown[] }` |
| `GET /api/v3/analytics/data-health` | `DataHealth` |
| `GET /api/v3/portfolio/summary` | `PortfolioSummary` |
| Errores | `{ code, message, details }`; se acepta también `{ detail }` de FastAPI |

Los importes pueden llegar como `number` o como `string` decimal; el frontend
normaliza ambos. Las fechas se asumen ISO (`YYYY-MM-DD`).

## Pantallas

| Ruta | Contenido |
|---|---|
| `/login` | Split-screen, email/password, mostrar contraseña, recordarme, loading, error genérico, acceso demo opcional |
| `/` | Flujo del mes, patrimonio, cuentas, cola “Por revisar”, gráfico 12 meses, categorías y salud de datos |
| `/movements` | Bandeja global con tabs en URL (`Todos`, `Por revisar`, `Duplicados`, `Transferencias`, `Sin categorizar`), filtros en URL, tabla densa y lista móvil, edición inline, aprobar/rechazar, selección masiva y cola de duplicados |
| `/imports` | Dropzone multi-formato (CSV/PDF/imagen/XLSX/OFX/QIF), cola de subida, historial y última importación |
| `/imports/[id]` | Detalle con pestañas `Resumen`, `Transacciones`, `Incidencias`, `Raw`, reconciliación y reproceso |
| `/accounts` | Tarjetas de cuentas, IBAN enmascarado, patrones, alta/edición, balance, transferencias sugeridas y conciliación |
| `/portfolio` | Posiciones, P&L, asignación, cobertura y avisos de posiciones negativas/datos incompletos |
| `/settings` | Secciones `General`, `Categorías`, `Reglas`, `Cuentas`, `Modelos`, `Privacidad`, `Datos` |
| `not-found`, `error`, `loading` | Estados globales; además skeletons/empty states por pantalla |

Diseño: tokens en `src/app/globals.css` (`--background`, `--foreground`,
`--muted`, `--border`, `--accent`, `--positive`, `--negative`, `--warning`),
sidebar de 240 px, topbar de 56 px, bottom nav de 5 en móvil, tema claro/oscuro/
sistema real, `prefers-reduced-motion`, foco visible y números tabulares.

## Mocks y TODOs

Los datos de ejemplo viven en `src/lib/mock.ts` y se activan:

- siempre con `NEXT_PUBLIC_DEMO_MODE=true`;
- si la API devuelve error de red, `404`, `501`, `502`, `503` o `504` (endpoint
  aún no implementado). **No** se enmascaran `401`, `403`, `422` ni `500`.

Pendiente de backend o de una siguiente iteración:

1. **Búsqueda global** de movimientos en la command palette (`/api/v3/search`).
2. **Persistencia de Ajustes**: General (perfil), Categorías, Reglas, Modelos,
   Privacidad y Datos son visuales; Guardar muestra un toast honesto. Sí están
   conectados el cambio de contraseña y la gestión de cuentas.
3. **Claves de modelos**: no se guardan ni se envían. El guardado real será
   server-side (env/secreto cifrado).
4. **Wizard de importación** de 3 pasos (analizar → previsualizar/mapear →
   confirmar). Ahora se sube la cola y se abre el informe; el detalle ya tiene
   las 4 pestañas.
5. **Revisión por tarjetas** (modo 1-a-1 del plan): pendiente. La tabla sí
   soporta `j/k` para mover el foco y `a/r/u` para aprobar, rechazar o reabrir
   el movimiento enfocado.
6. **Export/backup/restore** desde Ajustes: botones de contrato. En modo demo,
   Exportar CSV/JSON descarga datos de ejemplo; el resto no ejecuta acciones.
7. **Cuentas**: “probar patrón” solo estima coincidencias en modo demo; el alta y
   edición llaman a `/api/v3/accounts`. Falta el endpoint de preview.
8. **Duplicados**: la cola llama a `/api/v3/dedup-candidates` y resuelve con
   `mismo`/`distinto`; no hay fusión ni borrado.
9. **Cartera**: depende de que el backend sirva snapshots FIFO; las posiciones
   negativas se muestran solo en el aviso, no en la tabla.
10. **Toasts/undo**: el undo es optimista. En modo real vuelve a llamar a la API
    con el estado/categoría anterior; si el backend falla, se revierte la UI.
11. **Playwright/Lighthouse**: no se añadieron tests E2E en este scaffold. La
    comprobación visual se hizo manualmente con Chromium headless.

## Estructura

```
src/
  app/
    (app)/                 # shell protegido: dashboard, movimientos, imports, cuentas, cartera, ajustes
    login/                 # pantalla de acceso + formulario cliente
    layout.tsx             # metadata, tema sin flash, providers
    providers.tsx          # TanStack Query + tema + toasts
    globals.css            # tokens y base visual
    error.tsx / loading.tsx / not-found.tsx
  components/
    shell/                 # sidebar, topbar, bottom nav, command palette, theme toggle, user menu
    ui/                    # primitivas propias estilo shadcn (button, card, badges, form, feedback, toast)
    dashboard/ movements/ imports/ accounts/ portfolio/ settings/
  lib/
    api.ts                 # fetch tipado, CSRF, 401, endpoints v3
    types.ts               # contratos TypeScript
    auth.tsx               # AuthProvider, useMe, AuthGate
    theme.tsx              # tema claro/oscuro/sistema sin flash
    mock.ts                # datos deterministas del scaffold
    demo.ts                # demo mode + fallback seguro a mock
    utils.ts               # formatMoney/formatDate/cn/maskIban...
  middleware.ts            # puerta de sesión por presencia de cookie
```

## Notas de integración

- El backend v3 debe crear la cookie `ft_csrf` (legible por JS) junto a la de
  sesión. Si el nombre cambia, tocar `csrfToken()` en `src/lib/api.ts`.
- El login no envía CSRF porque aún no existe cookie CSRF; si el backend exige
  CSRF también aquí, habrá que exponer un endpoint de bootstrap o aceptar login
  sin token (recomendado: login exento + rate limit).
- `middleware.ts` no valida criptográficamente nada: es una puerta UX. La
  seguridad real está en `require_user` del backend.
- La mayoría de formularios de Ajustes no llaman a endpoints todavía; están
  separados en componentes para conectarlos uno a uno. Cambio de contraseña y
  cuentas ya usan la API real.
- No se importó nada de `frontend/`: el proyecto es independiente y compila por
  separado. `frontend/` queda intacto.
