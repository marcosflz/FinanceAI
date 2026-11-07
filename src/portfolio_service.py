"""Motor determinista de posiciones, FIFO y conciliación de cartera.

No usa ORM ni red. La integración decide qué operaciones, aperturas y snapshots
cargar; este módulo mantiene las reglas financieras y devuelve un resultado
serializable con incidencias explícitas.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Literal

ZERO = Decimal("0")
QTY_EPS = Decimal("0.00000001")
MONEY_EPS = Decimal("0.01")

OperationKind = Literal["BUY", "SELL", "FREE_RECEIPT", "DIVIDEND"]
CostStatus = Literal["known", "estimated", "unknown"]


def _dec(value: object) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


@dataclass(frozen=True)
class AssetOperation:
    id: int | str
    asset_id: str
    kind: OperationKind
    operation_date: date
    quantity: Decimal
    price: Decimal = ZERO
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    sequence: int = 0

    @property
    def absolute_quantity(self) -> Decimal:
        return abs(_dec(self.quantity))


@dataclass(frozen=True)
class OpeningPosition:
    asset_id: str
    as_of_date: date
    quantity: Decimal
    cost_total: Decimal | None = None
    cost_status: CostStatus = "unknown"
    source: str = "derived"

    @property
    def has_known_cost(self) -> bool:
        return self.cost_status in {"known", "estimated"} and self.cost_total is not None


@dataclass(frozen=True)
class SnapshotPosition:
    asset_id: str
    quantity: Decimal
    price: Decimal
    value: Decimal
    price_date: date | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    snapshot_date: date
    positions: tuple[SnapshotPosition, ...]
    cash_declared: Decimal | None = None
    currency: str = "EUR"


@dataclass
class Lot:
    asset_id: str
    quantity: Decimal
    cost_total: Decimal | None
    acquired_at: date
    source: str
    operation_id: int | str
    cost_status: CostStatus


@dataclass
class ReconciliationIssue:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    asset_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "asset_id": self.asset_id,
        }


@dataclass
class PositionCalculation:
    asset_id: str
    quantity: Decimal = ZERO
    cost_total: Decimal = ZERO
    cost_known_quantity: Decimal = ZERO
    cost_unknown_quantity: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    realized_complete: bool = True
    fees: Decimal = ZERO
    dividends: Decimal = ZERO
    lots: list[Lot] = field(default_factory=list)
    snapshot_quantity: Decimal | None = None
    quantity_difference: Decimal | None = None
    market_price: Decimal | None = None
    market_value: Decimal | None = None
    market_price_date: date | None = None
    pnl_unrealized: Decimal | None = None
    issues: list[ReconciliationIssue] = field(default_factory=list)

    @property
    def cost_coverage(self) -> Decimal:
        if self.quantity <= QTY_EPS:
            return Decimal("1")
        return min(Decimal("1"), self.cost_known_quantity / self.quantity)

    @property
    def average_cost(self) -> Decimal | None:
        if self.cost_known_quantity <= QTY_EPS:
            return None
        return self.cost_total / self.cost_known_quantity

    @property
    def cost_complete(self) -> bool:
        return (
            self.quantity > QTY_EPS
            and self.cost_unknown_quantity <= QTY_EPS
            and self.cost_known_quantity > QTY_EPS
        )

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "cantidad": str(self.quantity),
            "coste_total": str(self.cost_total),
            "coste_conocido": str(self.cost_total),
            "cantidad_coste_conocido": str(self.cost_known_quantity),
            "cantidad_coste_desconocido": str(self.cost_unknown_quantity),
            "cobertura_coste": str(self.cost_coverage),
            "precio_medio": str(self.average_cost) if self.average_cost is not None else None,
            "pnl_realizado": str(self.realized_pnl),
            "pnl_realizado_completo": self.realized_complete,
            "comisiones": str(self.fees),
            "dividendos": str(self.dividends),
            "cantidad_declarada": (
                str(self.snapshot_quantity) if self.snapshot_quantity is not None else None
            ),
            "diferencia_cantidad": (
                str(self.quantity_difference)
                if self.quantity_difference is not None
                else None
            ),
            "precio_actual": str(self.market_price) if self.market_price is not None else None,
            "valor_actual": str(self.market_value) if self.market_value is not None else None,
            "precio_fecha": self.market_price_date.isoformat() if self.market_price_date else None,
            "pnl_no_realizado": (
                str(self.pnl_unrealized) if self.pnl_unrealized is not None else None
            ),
            "incidencias": [issue.as_dict() for issue in self.issues],
        }


def _add_lot(lots: list[Lot], lot: Lot) -> None:
    if lot.quantity > QTY_EPS:
        lots.append(lot)


def _consume_lots(
    lots: list[Lot],
    *,
    asset_id: str,
    quantity: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Consume FIFO y devuelve (conocido, desconocido, coste conocido)."""
    remaining = quantity
    known_quantity = ZERO
    unknown_quantity = ZERO
    known_cost = ZERO
    for lot in lots:
        if remaining <= QTY_EPS:
            break
        if lot.quantity <= QTY_EPS:
            continue
        take = min(remaining, lot.quantity)
        if lot.cost_total is None:
            unknown_quantity += take
        else:
            unit_cost = lot.cost_total / lot.quantity
            known_cost += unit_cost * take
            known_quantity += take
            lot.cost_total -= unit_cost * take
        lot.quantity -= take
        remaining -= take
    lots[:] = [lot for lot in lots if lot.quantity > QTY_EPS]
    return known_quantity, unknown_quantity, known_cost


def _reconcile_position(
    calc: PositionCalculation,
    snapshot_position: SnapshotPosition | None,
) -> None:
    if snapshot_position is None:
        if calc.quantity > QTY_EPS:
            calc.issues.append(ReconciliationIssue(
                code="missing_snapshot_position",
                severity="info",
                message="La posición no aparece en el snapshot más reciente.",
                asset_id=calc.asset_id,
            ))
        return

    calc.snapshot_quantity = snapshot_position.quantity
    calc.quantity_difference = calc.quantity - snapshot_position.quantity
    if abs(calc.quantity_difference) > QTY_EPS:
        calc.issues.append(ReconciliationIssue(
            code="snapshot_quantity_mismatch",
            severity="error",
            message=(
                "La cantidad calculada no coincide con el snapshot: "
                f"{calc.quantity} frente a {snapshot_position.quantity}."
            ),
            asset_id=calc.asset_id,
        ))

    declared_value = snapshot_position.value
    computed_value = snapshot_position.quantity * snapshot_position.price
    # El precio unitario del snapshot viene redondeado a céntimos; para muchas
    # participaciones, multiplicar ese precio redondeado y compararlo con el
    # valor declarado deja una diferencia legítima de céntimos.
    value_tolerance = max(
        MONEY_EPS,
        snapshot_position.quantity * Decimal("0.005") + MONEY_EPS,
    )
    if declared_value is not None and abs(computed_value - declared_value) > value_tolerance:
        calc.issues.append(ReconciliationIssue(
            code="snapshot_value_mismatch",
            severity="warning",
            message=(
                "Cantidad por precio no coincide con el valor declarado: "
                f"{computed_value} frente a {declared_value}."
            ),
            asset_id=calc.asset_id,
        ))

    calc.market_price = snapshot_position.price
    calc.market_price_date = snapshot_position.price_date
    calc.market_value = declared_value
    if (
        calc.cost_complete
        and declared_value is not None
        and abs(calc.quantity_difference or ZERO) <= QTY_EPS
    ):
        calc.pnl_unrealized = declared_value - calc.cost_total


def rebuild_asset(
    *,
    asset_id: str,
    operations: Iterable[AssetOperation],
    opening: OpeningPosition | None = None,
    snapshot_position: SnapshotPosition | None = None,
) -> PositionCalculation:
    """Reconstruye una posición aplicando apertura + operaciones posteriores."""
    calc = PositionCalculation(asset_id=asset_id)
    lots: list[Lot] = []

    if opening is not None:
        if opening.quantity < -QTY_EPS:
            calc.issues.append(ReconciliationIssue(
                code="negative_opening_position",
                severity="error",
                message="La posición de apertura es negativa.",
                asset_id=asset_id,
            ))
        elif opening.quantity > QTY_EPS:
            _add_lot(lots, Lot(
                asset_id=asset_id,
                quantity=opening.quantity,
                cost_total=opening.cost_total if opening.has_known_cost else None,
                acquired_at=opening.as_of_date,
                source=opening.source,
                operation_id=f"opening:{opening.as_of_date.isoformat()}",
                cost_status=opening.cost_status,
            ))
        cutoff = opening.as_of_date
    else:
        cutoff = None

    ordered = sorted(
        (
            operation
            for operation in operations
            if cutoff is None or operation.operation_date > cutoff
        ),
        key=lambda operation: (
            operation.operation_date,
            operation.sequence,
            str(operation.id),
        ),
    )

    for operation in ordered:
        quantity = operation.absolute_quantity
        if operation.kind == "DIVIDEND":
            calc.dividends += _dec(operation.price) + _dec(operation.tax)
            continue
        if operation.kind == "BUY":
            fee = abs(_dec(operation.fee))
            tax = abs(_dec(operation.tax))
            cost = quantity * abs(_dec(operation.price)) + fee + tax
            calc.fees += fee
            _add_lot(lots, Lot(
                asset_id=asset_id,
                quantity=quantity,
                cost_total=cost,
                acquired_at=operation.operation_date,
                source="buy",
                operation_id=operation.id,
                cost_status="known",
            ))
            continue
        if operation.kind == "FREE_RECEIPT":
            value = quantity * abs(_dec(operation.price))
            fee = abs(_dec(operation.fee))
            calc.fees += fee
            _add_lot(lots, Lot(
                asset_id=asset_id,
                quantity=quantity,
                cost_total=(value + fee) if value > 0 else None,
                acquired_at=operation.operation_date,
                source="free_receipt",
                operation_id=operation.id,
                cost_status="known" if value > 0 else "unknown",
            ))
            continue

        # SELL
        if quantity <= QTY_EPS:
            continue
        fee = abs(_dec(operation.fee))
        tax = abs(_dec(operation.tax))
        calc.fees += fee + tax
        known_qty, unknown_qty, known_cost = _consume_lots(
            lots, asset_id=asset_id, quantity=quantity
        )
        available_qty = known_qty + unknown_qty
        oversold = quantity - available_qty
        proceeds = quantity * abs(_dec(operation.price)) - fee - tax
        if known_qty > QTY_EPS:
            calc.realized_pnl += (
                proceeds * (known_qty / quantity) - known_cost
            )
        if unknown_qty > QTY_EPS or oversold > QTY_EPS:
            calc.realized_complete = False
        if oversold > QTY_EPS:
            calc.issues.append(ReconciliationIssue(
                code="position_oversold",
                severity="error",
                message=f"Venta de {quantity} sin lotes suficientes ({oversold} de exceso).",
                asset_id=asset_id,
            ))

    calc.lots = [lot for lot in lots if lot.quantity > QTY_EPS]
    calc.cost_total = sum(
        (lot.cost_total for lot in calc.lots if lot.cost_total is not None),
        ZERO,
    )
    calc.cost_known_quantity = sum(
        (lot.quantity for lot in calc.lots if lot.cost_total is not None),
        ZERO,
    )
    calc.cost_unknown_quantity = sum(
        (lot.quantity for lot in calc.lots if lot.cost_total is None),
        ZERO,
    )
    calc.quantity = sum((lot.quantity for lot in calc.lots), ZERO)
    sold_quantity = sum(
        (
            operation.absolute_quantity
            for operation in ordered
            if operation.kind == "SELL"
        ),
        ZERO,
    )
    calc.quantity = (
        (opening.quantity if opening is not None else ZERO)
        + sum(
            (
                operation.absolute_quantity
                for operation in ordered
                if operation.kind in {"BUY", "FREE_RECEIPT"}
            ),
            ZERO,
        )
        - sold_quantity
    )

    if calc.quantity < -QTY_EPS:
        calc.issues.append(ReconciliationIssue(
            code="negative_position",
            severity="error",
            message="La posición calculada es negativa; falta una apertura o una compra.",
            asset_id=asset_id,
        ))
    if calc.quantity > QTY_EPS and calc.cost_unknown_quantity > QTY_EPS:
        calc.issues.append(ReconciliationIssue(
            code="unknown_cost_basis",
            severity="warning",
            message="Parte de la posición no tiene coste de adquisición demostrable.",
            asset_id=asset_id,
        ))

    _reconcile_position(calc, snapshot_position)
    return calc


def rebuild_portfolio(
    *,
    operations: Iterable[AssetOperation],
    openings: Iterable[OpeningPosition] = (),
    snapshot: PortfolioSnapshot | None = None,
    cash_calculated: Decimal | None = None,
) -> dict:
    """Reconstruye todas las posiciones y añade conciliación de efectivo."""
    grouped_operations: dict[str, list[AssetOperation]] = defaultdict(list)
    for operation in operations:
        grouped_operations[operation.asset_id].append(operation)

    opening_by_asset: dict[str, OpeningPosition] = {}
    for opening in openings:
        current = opening_by_asset.get(opening.asset_id)
        if current is None or opening.as_of_date < current.as_of_date:
            opening_by_asset[opening.asset_id] = opening

    snapshot_by_asset: dict[str, SnapshotPosition] = {}
    if snapshot is not None:
        for item in snapshot.positions:
            snapshot_by_asset[item.asset_id] = item

    asset_ids = set(grouped_operations) | set(opening_by_asset) | set(snapshot_by_asset)
    positions = [
        rebuild_asset(
            asset_id=asset_id,
            operations=grouped_operations.get(asset_id, []),
            opening=opening_by_asset.get(asset_id),
            snapshot_position=snapshot_by_asset.get(asset_id),
        )
        for asset_id in sorted(asset_ids)
    ]

    issues = [
        issue
        for position in positions
        for issue in position.issues
    ]
    for asset_id, snapshot_position in snapshot_by_asset.items():
        if (
            asset_id not in grouped_operations
            and asset_id not in opening_by_asset
            and snapshot_position.quantity > QTY_EPS
        ):
            issues.append(ReconciliationIssue(
                code="missing_opening_position",
                severity="error",
                message=(
                    "El snapshot contiene una posición sin operaciones ni apertura: "
                    f"{snapshot_position.quantity}."
                ),
                asset_id=asset_id,
            ))

    cash_difference = None
    if (
        snapshot is not None
        and snapshot.cash_declared is not None
        and cash_calculated is not None
    ):
        cash_difference = _dec(snapshot.cash_declared) - _dec(cash_calculated)
        if abs(cash_difference) > MONEY_EPS:
            issues.append(ReconciliationIssue(
                code="cash_snapshot_difference",
                severity="error",
                message=(
                    "El efectivo del snapshot no coincide con el calculado: "
                    f"{snapshot.cash_declared} frente a {cash_calculated}."
                ),
            ))

    return {
        "posiciones": [position.as_dict() for position in positions],
        "incidencias": [issue.as_dict() for issue in issues],
        "total_cost": str(sum((position.cost_total for position in positions), ZERO)),
        "total_market": str(sum((position.market_value or ZERO for position in positions), ZERO)),
        "total_realized": str(sum((position.realized_pnl for position in positions), ZERO)),
        "total_unrealized": str(sum(
            (
                position.pnl_unrealized or ZERO
                for position in positions
                if position.pnl_unrealized is not None
            ),
            ZERO,
        )),
        "total_fees": str(sum((position.fees for position in positions), ZERO)),
        "total_dividends": str(sum((position.dividends for position in positions), ZERO)),
        "unknown_cost_positions": sum(
            1 for position in positions if not position.cost_complete and position.quantity > QTY_EPS
        ),
        "cash_difference": str(cash_difference) if cash_difference is not None else None,
        "snapshot_date": snapshot.snapshot_date.isoformat() if snapshot else None,
    }
