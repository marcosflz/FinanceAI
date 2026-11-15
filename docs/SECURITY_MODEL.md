# Modelo de seguridad: multi-tenant con SQLite cifrado por usuario

> Fecha: 2026-11-15. Aplica con `TENANT_MODE=per_user` y `TENANT_ENCRYPTION=true`.
> En `TENANT_MODE=single` (por defecto) la app sigue funcionando como antes:
> una BD con todo y sin cifrado por usuario.

## Qué protege y qué no

**Protege (datos en reposo):** el disco del servidor, los backups y un
administrador que lea ficheros. Cada usuario tiene su SQLite cifrado con
SQLCipher 4 (AES-256) y sus extractos/cachés cifrados con AES-256-GCM. Sin su
contraseña o su clave de recuperación no se pueden descifrar.

**No protege:**

- un root que vuelque la memoria del proceso o despliegue código modificado
  mientras el usuario tiene la sesión abierta (la DEK está en RAM durante la
  petición y en el pool del motor hasta `TENANT_IDLE_SECONDS`);
- lo que el asistente envía al proveedor de IA que el usuario configura
  (movimientos, importes, comercios consultados);
- metadatos de la BD central: email, fechas de acceso, número de trabajos en
  cola y **cuándo** toca ejecutar cada automatización (no qué hace);
- el tamaño de los ficheros del tenant.

## Jerarquía de claves (`src/auth/keys.py`)

| Clave | Origen | Dónde vive |
|---|---|---|
| **DEK** (32 B) | aleatoria, una por usuario | nunca en claro en disco |
| **KEK** | Argon2id(contraseña, sal propia; t=3, m=64 MiB, p=4) | se deriva en el login |
| Clave de sesión | HKDF(token en claro de la cookie) | solo en la cookie del navegador |
| Clave de recuperación | 32 caracteres (~160 bits), se muestra una vez | la guarda el usuario |
| Clave de worker | X25519 efímera por proceso | solo en RAM del worker |
| Subclave de ficheros | HKDF(DEK, "ft-files") | derivada al usarla |

La BD central guarda la DEK **envuelta** (AES-256-GCM, AAD con id de usuario y
propósito) con la KEK (`users.dek_wrapped_pw`), con la clave de recuperación
(`users.dek_wrapped_recovery`), con la clave de cada sesión
(`sessions.dek_wrapped`) y, si hay concesión, sellada para un worker
(`key_leases.sealed_dek`, ECIES X25519). Como de las sesiones solo se guarda el
SHA-256 del token, ningún blob se puede abrir con lo que hay en disco.

El hash de login (`users.password_hash`) y la KEK usan sales distintas:
verificar la contraseña no permite descifrar nada.

## Flujos

- **Primer login** (o primer login tras migrar a `per_user`): se genera la DEK
  y la clave de recuperación; el login responde `recovery_key` una sola vez.
- **Cada petición**: `require_user` desenvuelve la DEK con el token de la
  cookie y fija el `TenantContext` (`src/db/tenant.py`). `_session()` abre el
  SQLite del usuario; sin contexto lanza `NoTenantContext`.
- **Rotación de sesión (24 h)**: se re-envuelve la DEK con el token nuevo.
- **Cambio de contraseña**: solo se re-envuelve la DEK (no hay `PRAGMA rekey`)
  y se revocan las sesiones.
- **Recuperación** (`POST /auth/recover`): la clave de recuperación desenvuelve
  la DEK, se fija contraseña nueva y se emite otra clave de recuperación.
- **Sin contraseña ni clave de recuperación los datos son irrecuperables.**
  `scripts/set_password.py` cambia el hash pero no puede re-envolver la DEK:
  en `per_user` cifrado no sirve para recuperar una cuenta.
- **Alta de usuarios**: solo por invitación (`POST /admin/users`). El invitado
  elige su contraseña en `/invite?token=…`; el admin nunca la conoce.

## Worker, importaciones y automatizaciones (concesión solo en RAM)

1. Al arrancar, el worker genera un par X25519 y publica la pública en
   `worker_keys` (latido cada 30 s).
2. Cuando el usuario está presente (petición autenticada) y tiene trabajos en
   cola o automatizaciones activas, la API sella su DEK para cada worker vivo
   (`key_leases`): `import` dura 6 h; `automation` hasta `users.automation_until`
   (opt-in en Ajustes → Seguridad, máx. `AUTOMATION_LEASE_DAYS`).
3. El worker reclama un `central_jobs`, abre la concesión con su privada y
   procesa dentro de `use_tenant(...)`.
4. Si el worker se reinicia, su privada desaparece: los trabajos pasan a
   `waiting_unlock` y se reencolan en la siguiente petición del usuario.

Nunca se guarda en disco una clave capaz de abrir los datos sin el usuario.

## Ficheros (`src/storage.py`)

`TENANT_DIR/<tenant>/finance.db` (SQLCipher) y `TENANT_DIR/<tenant>/files/`
(extractos y cachés de extracción cifrados, formato `FTENC1`). Para procesarlos
se descifran a un temporal que se borra al terminar: en Docker `/tmp` es tmpfs.

## Portabilidad

`POST /api/v3/export/database` (exige la contraseña) descarga el SQLite:
`format=sqlite` (descifrado, abrible con cualquier herramienta) o
`format=sqlcipher` con una passphrase elegida (DB Browser for SQLite/SQLCipher
o `sqlcipher`: `PRAGMA key = '<passphrase>'`).

## Operación

- `alembic -c alembic_central.ini upgrade head` migra la central (el entrypoint
  lo hace). Cada SQLite de usuario se migra a head al abrirse
  (`migrate_tenant_engine`), porque hace falta su clave.
- Los scripts de mantenimiento que usan `_session()` (reimport, seeds…) solo
  funcionan en modo `single`: en `per_user` el admin no tiene las claves.
- Backups: copiar `central.db` y `TENANT_DIR` tal cual; van cifrados.
