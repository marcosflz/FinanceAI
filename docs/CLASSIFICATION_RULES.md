# Reglas de clasificación base

> Referencia histórica. `scripts/seed_rules.py` se archivó el 2026-11-04
> (`~/financial-tools-backups/repo-cleanup-20261104/scripts/`). `reset_v2`
> deja la tabla vacía; las reglas vigentes se siembran con
> `python -m scripts.seed_reimport_rules`.

## Reglas MCC → categoría

Fuente autoritativa: `scripts/seed_rules.py` (`MCC_CATEGORY_MAP`).

| Categoría | MCC |
|---|---|
| Alimentación | 5411, 5422, 5441, 5451, 5462, 5499 |
| Compras | 5200, 5262, 5310, 5311, 5399, 5611, 5621, 5631, 5641, 5651, 5661, 5681, 5691, 5699, 5940, 5941, 5942, 5943, 5944, 5945, 5946, 5947, 5948, 5949, 5963, 5977, 5999 |
| Inversiones | 6211 |
| Ocio | 5812, 5813, 5814, 5816, 5818, 7512, 7832, 7841, 7911, 7922, 7932, 7933, 7941, 7991, 7992, 7993, 7994, 7995, 7996, 7997, 7998 |
| Salud | 5912, 8011, 8021, 8031, 8041, 8042, 8043, 8049, 8050, 8062, 8071, 8099 |
| Servicios | 5734, 5967, 7230, 7372, 9399 |
| Telecomunicaciones | 4814, 4816, 4821, 4899, 5815 |
| Transporte | 4111, 4112, 4121, 4131, 4784, 5541, 5542, 5983, 7523 |
| Vivienda | 4900, 5211, 5231, 5251, 5712, 5713, 5714, 5718, 5719, 5722, 5732 |

## Reglas de merchant → categoría

Fuente autoritativa: `scripts/seed_rules.py` (`MERCHANT_CATEGORY_MAP`).

| Merchant (contiene) | Categoría |
|---|---|
| ALCALA COMICS | Ocio |
| AUCALSA | Transporte |
| BRISA RESIDENCIAL | Vivienda |
| CASTELLANA DE AUTOPISTAS | Transporte |
| DIGI SPAIN | Telecomunicaciones |
| DNI/PASAPORTE | Servicios |
| DRUNI | Compras |
| IKEA | Compras |
| KARTING | Ocio |
| MOVILIDAD MMD | Transporte |
| PLAYSTATION | Ocio |
| RITUALS | Compras |
| SEITT | Transporte |
| SUNFLOWER SOLUCIONES | Servicios |
| TOTALENERGIES | Vivienda |
| UTE AGUAS ALCALA | Vivienda |
| WAYLET | Transporte |

## Reglas aprendidas

Las reglas generadas desde el histórico se crean con
`GET/POST /api/v2/classification-rules/autolearn` y se aplican desde
`/movements`. No forman parte del seed base y no se recrean al resetear.

