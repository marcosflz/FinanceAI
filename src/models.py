from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, LargeBinary,
    Boolean, Text, Numeric, Date, UniqueConstraint, Index, text,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Documento(Base):
    """Documento financiero subido al sistema (PDF de extracto bancario, etc.)."""

    __tablename__ = "documentos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256
    size_bytes = Column(Integer, nullable=True)
    contenido = Column(LargeBinary, nullable=True)  # archivo almacenado en BD
    num_movimientos = Column(Integer, default=0)
    saldo_inicial = Column(Float, nullable=True)   # saldo al inicio del periodo (del extracto)
    saldo_final = Column(Float, nullable=True)     # saldo al final del periodo (del extracto)
    subido_en = Column(DateTime, default=datetime.utcnow)
    parseado_en = Column(DateTime, nullable=True)
    parseado = Column(Boolean, default=False)
    aplicado = Column(Boolean, default=False)

    movimientos = relationship(
        "Movimiento", back_populates="documento", cascade="all, delete-orphan"
    )


class Movimiento(Base):
    """Movimiento financiero extraído de un documento."""

    __tablename__ = "movimientos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    documento_id = Column(
        Integer, ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concepto = Column(String(500), nullable=False)
    concepto_original = Column(String(500), nullable=True)  # snapshot inmutable del LLM, nunca editado
    valor = Column(Float, nullable=False)
    categoria = Column(String(100), nullable=True)
    tipo = Column(String(50), nullable=True)   # ingreso | gasto | movimiento_interno
    subtipo = Column(String(50), nullable=True)  # gastos: fijo|variable|inversion  ·  ingresos: nomina|variable|inversion
    timestamp = Column(DateTime, nullable=True)  # fecha del movimiento financiero
    aprobado = Column(Boolean, nullable=True)  # None=pendiente, True=aprobado, False=rechazado
    mov_hash = Column(String(64), nullable=True, index=True)  # SHA-256(timestamp|valor|concepto_original) para dedup cross-documento
    descripcion_llm = Column(String(1000), nullable=True)  # explicación en lenguaje natural generada por el LLM

    documento = relationship("Documento", back_populates="movimientos")
    etiquetas = relationship("MovimientoEtiqueta", back_populates="movimiento", cascade="all, delete-orphan")


class Pocket(Base):
    """Sobre virtual de ahorro/presupuesto (envelope budgeting)."""

    __tablename__ = "pockets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(String(500), nullable=True)
    objetivo = Column(Float, nullable=True)           # importe total a acumular (None = sin límite)
    aportacion_mensual = Column(Float, nullable=True) # objetivo de aportación mensual (referencia para avisos)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    transacciones = relationship(
        "PocketTransaccion", back_populates="pocket", cascade="all, delete-orphan"
    )


class PocketTransaccion(Base):
    """Aportación o retiro sobre un pocket concreto."""

    __tablename__ = "pocket_transacciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pocket_id = Column(Integer, ForeignKey("pockets.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)          # 'aportacion' | 'retiro'
    importe = Column(Float, nullable=False)            # siempre positivo; tipo determina dirección
    nota = Column(String(500), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    documento_id = Column(Integer, ForeignKey("documentos.id", ondelete="SET NULL"), nullable=True, index=True)
    movimiento_id = Column(Integer, ForeignKey("movimientos.id", ondelete="SET NULL"), nullable=True, index=True)

    pocket = relationship("Pocket", back_populates="transacciones")
    documento = relationship("Documento")
    movimiento = relationship("Movimiento")


class Categoria(Base):
    """Categoría de movimiento configurable y jerárquica.

    ``aplica_a`` indica la tipología del movimiento a la que se puede asignar
    (``gasto``, ``ingreso`` o ``ambos``). ``tratamiento`` distingue las
    categorías normales de transferencias e inversiones, que quedan fuera de
    los KPIs de gasto/ingreso.
    """

    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(255), nullable=False)
    parent_id = Column(
        Integer, ForeignKey("categorias.id", ondelete="SET NULL"), nullable=True, index=True
    )
    aplica_a = Column(String(10), nullable=False, default="gasto")  # gasto|ingreso|ambos
    tratamiento = Column(String(20), nullable=False, default="normal")  # normal|transferencia|inversion
    color = Column(String(20), nullable=False, default="#6366f1")
    excluir_kpis = Column(Boolean, nullable=False, default=False)
    orden = Column(Integer, nullable=False, default=100)
    system_key = Column(String(40), nullable=True, unique=True)
    es_default = Column(Boolean, nullable=False, default=False)
    descripcion = Column(String(500), nullable=True)
    activa = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship(
        "Categoria",
        remote_side=[id],
        back_populates="children",
    )
    children = relationship(
        "Categoria",
        back_populates="parent",
        cascade="all",
        order_by="Categoria.orden",
    )

    __table_args__ = (
        # Nombre único dentro de cada padre. Los nombres pueden repetirse en
        # ramas distintas (p. ej. "Otros" en varias categorías).
        Index(
            "uq_categorias_parent_nombre",
            text("COALESCE(parent_id, 0)"),
            text("lower(nombre)"),
            unique=True,
        ),
        Index("ix_categorias_parent_default", "parent_id", "es_default"),
    )


class TagGroup(Base):
    """Agrupación opcional de etiquetas (Viajes, Recurrencia, …)."""

    __tablename__ = "tag_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False, unique=True)
    color = Column(String(20), nullable=False, default="#6366f1")
    orden = Column(Integer, nullable=False, default=100)
    creado_en = Column(DateTime, default=datetime.utcnow)

    etiquetas = relationship(
        "Etiqueta", back_populates="group", passive_deletes=True
    )


class Etiqueta(Base):
    """Etiqueta libre asignable a movimientos para filtros personalizados."""

    __tablename__ = "etiquetas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False, unique=True)
    color = Column(String(20), nullable=False, default="#6366f1")
    descripcion = Column(String(500), nullable=True)
    group_id = Column(
        Integer, ForeignKey("tag_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    orden = Column(Integer, nullable=False, default=100)
    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    group = relationship("TagGroup", back_populates="etiquetas")
    movimientos = relationship(
        "MovimientoEtiqueta", back_populates="etiqueta", cascade="all, delete-orphan"
    )


class MovimientoEtiqueta(Base):
    """Relación M2M entre movimientos y etiquetas."""

    __tablename__ = "movimiento_etiquetas"

    movimiento_id = Column(
        Integer, ForeignKey("movimientos.id", ondelete="CASCADE"), primary_key=True
    )
    etiqueta_id = Column(
        Integer, ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True
    )

    etiqueta = relationship("Etiqueta", back_populates="movimientos")
    movimiento = relationship("Movimiento", back_populates="etiquetas")


class MovementTag(Base):
    """Etiqueta libre aplicada a un movimiento v3 (financial_movements)."""

    __tablename__ = "movement_tags"

    movement_id = Column(
        Integer,
        ForeignKey("financial_movements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id = Column(
        Integer,
        ForeignKey("etiquetas.id", ondelete="CASCADE"),
        primary_key=True,
    )
    origen = Column(String(10), nullable=False, default="user")  # user|rule|decider
    creado_en = Column(DateTime, default=datetime.utcnow)

    etiqueta = relationship("Etiqueta")
    movement = relationship("FinancialMovement")

    __table_args__ = (Index("ix_movement_tags_tag_id", "tag_id"),)


class AppConfig(Base):
    """Configuración de la aplicación como pares clave-valor."""

    __tablename__ = "app_config"

    key = Column(String(200), primary_key=True)
    value = Column(Text, nullable=True)


class Subtipo(Base):
    """Subtipo de movimiento configurable por el usuario."""

    __tablename__ = "subtipos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)       # e.g. "fijo", "variable", "nómina"
    tipo = Column(String(20), nullable=False)           # "gasto" | "ingreso"
    descripcion = Column(String(500), nullable=True)   # usado en los prompts del LLM
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("nombre", "tipo", name="uq_subtipo_nombre_tipo"),)


# ── CARTERA (Renta Variable) ────────────────────────────────────────────────


class Activo(Base):
    """Activo de renta variable configurado en la cartera (acción, ETF, crypto)."""

    __tablename__ = "activos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), nullable=False, unique=True, index=True)  # e.g. "AAPL", "BTC-USD", "VWCE.DE"
    nombre = Column(String(255), nullable=True)         # nombre descriptivo (se puede rellenar desde yfinance)
    tipo_activo = Column(String(20), nullable=False)    # "accion" | "etf" | "crypto"
    exchange = Column(String(100), nullable=True)       # mercado (NASDAQ, XETRA…)
    moneda = Column(String(10), nullable=False, default="EUR")
    notas = Column(String(500), nullable=True)
    activo = Column(Boolean, default=True)              # False = archivado (soft-delete)
    creado_en = Column(DateTime, default=datetime.utcnow)

    operaciones = relationship(
        "Operacion", back_populates="activo", cascade="all, delete-orphan"
    )
    etiquetas = relationship(
        "ActivoEtiqueta", back_populates="activo", cascade="all, delete-orphan"
    )


class ActivoEtiqueta(Base):
    """Relación M2M entre activos y etiquetas (reutiliza la tabla Etiqueta existente)."""

    __tablename__ = "activo_etiquetas"

    activo_id = Column(
        Integer, ForeignKey("activos.id", ondelete="CASCADE"), primary_key=True
    )
    etiqueta_id = Column(
        Integer, ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True
    )

    activo = relationship("Activo", back_populates="etiquetas")
    etiqueta = relationship("Etiqueta")


class Operacion(Base):
    """Operación de compra o venta sobre un activo de la cartera."""

    __tablename__ = "operaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activo_id = Column(
        Integer, ForeignKey("activos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo = Column(String(20), nullable=False)            # "compra" | "venta"
    cantidad = Column(Float, nullable=False)             # nº acciones/participaciones/unidades
    precio_unitario = Column(Float, nullable=False)      # precio por unidad en la moneda del activo
    comision = Column(Float, nullable=False, default=0)  # costes de la operación
    moneda = Column(String(10), nullable=True)  # divisa de precio_unitario y comision (NULL = divisa del activo)
    fecha = Column(DateTime, nullable=False)
    nota = Column(String(500), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    movimiento_id = Column(
        Integer, ForeignKey("movimientos.id", ondelete="SET NULL"), nullable=True, index=True
    )  # movimiento de inversión vinculado (opcional)

    activo = relationship("Activo", back_populates="operaciones")
    movimiento = relationship("Movimiento")


# ── NUEVO MODELO (v2) — INGESTA ──────────────────────────────────────────────


class SourceFile(Base):
    """Archivo importado (CSV, PDF legacy, etc.)."""

    __tablename__ = "source_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(40), nullable=False)          # 'trade_republic_csv' | 'pdf_legacy' | …
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=False)       # SHA-256 contenido
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    row_count = Column(Integer, nullable=True)
    movement_new_count = Column(Integer, nullable=True)
    movement_seen_count = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="uploaded")
    parser_version = Column(String(20), nullable=False)
    storage_path = Column(String(500), nullable=True)    # ruta al archivo en disco
    mime_type = Column(String(100), nullable=True)
    page_count = Column(Integer, nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    balance_start = Column(Numeric(18, 4), nullable=True)
    balance_end = Column(Numeric(18, 4), nullable=True)
    balance_start_date = Column(Date, nullable=True)
    extraction_meta = Column(Text, nullable=True)       # JSON del extractor agéntico
    error = Column(Text, nullable=True)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    subido_en = Column(DateTime, default=datetime.utcnow)
    parseado_en = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "file_hash", name="uq_source_file"),
    )


class RawRow(Base):
    """Fila cruda de un archivo importado (payload JSON inmutable)."""

    __tablename__ = "raw_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)          # JSON string (compatible SQLite/Postgres)
    row_hash = Column(String(64), nullable=False)
    page = Column(Integer, nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    unit_type = Column(String(30), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_file_id", "row_index", name="uq_raw_row_idx"),
    )

    source_file = relationship("SourceFile")


class NormalizedEvent(Base):
    """Evento normalizado: hecho determinista del broker, inmutable."""

    __tablename__ = "normalized_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_row_id = Column(
        Integer, ForeignKey("raw_rows.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    source_txn_id = Column(String(64), nullable=True)       # transaction_id del broker
    broker_type = Column(String(40), nullable=False)        # 'CARD_TRANSACTION'…
    kind = Column(String(30), nullable=False)               # enum canónico
    occurred_at = Column(DateTime, nullable=True)           # datetime: timestamp de apunte
    value_date = Column(Date, nullable=False)               # date: fecha valor
    amount = Column(Numeric(18, 4), nullable=True)          # signado; NULL si no hay cash
    currency = Column(String(3), nullable=False, default="EUR")
    fee = Column(Numeric(18, 4), nullable=True)
    tax = Column(Numeric(18, 4), nullable=True)
    original_amount = Column(Numeric(18, 4), nullable=True)
    original_currency = Column(String(3), nullable=True)
    fx_rate = Column(Numeric(18, 8), nullable=True)
    asset_symbol = Column(String(20), nullable=True)        # ISIN o ticker crypto
    asset_name = Column(String(255), nullable=True)
    asset_class = Column(String(20), nullable=True)         # stock|etf|fondo|cripto
    shares = Column(Numeric(24, 10), nullable=True)
    price = Column(Numeric(18, 6), nullable=True)
    counterparty_name = Column(String(255), nullable=True)
    counterparty_iban = Column(String(34), nullable=True)
    mcc_code = Column(String(4), nullable=True)
    description_raw = Column(Text, nullable=True)
    description_clean = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    fingerprint = Column(String(64), nullable=False)        # SHA-256 canónico
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    dedup_key = Column(String(128), nullable=True)
    occurrence_index = Column(Integer, nullable=False, default=0)
    extraction_confidence = Column(Numeric(4, 3), nullable=True)

    raw_row = relationship("RawRow")

    __table_args__ = (
        Index("ix_ne_source_txn_id", "source_txn_id"),
        Index("ix_ne_fingerprint", "fingerprint"),
        Index("ix_ne_value_date", "value_date"),
        Index("ix_ne_dedup_key", "dedup_key"),
    )


class Account(Base):
    """Cuenta (broker central o cuenta externa propia)."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    iban = Column(String(34), nullable=True, unique=True)
    alias_patrones = Column(Text, nullable=True)    # JSON array de patrones/regex
    tipo = Column(String(20), nullable=False, default="efectivo_externa")
    broker = Column(String(40), nullable=True)
    es_propia = Column(Boolean, default=True)
    moneda = Column(String(3), default="EUR")
    color = Column(String(7), default="#6366f1")
    balance_inicial = Column(Numeric(18, 4), nullable=True)
    balance_inicial_fecha = Column(Date, nullable=True)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class AccountCurrencyBalance(Base):
    """Ancla de saldo inicial y conciliación por cuenta y divisa."""

    __tablename__ = "account_currency_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    currency = Column(String(3), nullable=False, default="EUR")
    balance_inicial = Column(Numeric(18, 4), nullable=True)
    balance_inicial_eur = Column(Numeric(18, 4), nullable=True)
    balance_inicial_fecha = Column(Date, nullable=True)
    last_reconciled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account")

    __table_args__ = (
        UniqueConstraint(
            "account_id", "currency", name="uq_account_currency_balance"
        ),
        Index("ix_acb_account_currency", "account_id", "currency"),
    )


class FinancialMovement(Base):
    """Movimiento financiero canónico — entidad central de negocio."""

    __tablename__ = "financial_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        Integer, ForeignKey("normalized_events.id"),
        nullable=False, unique=True,
    )
    account_id = Column(
        Integer, ForeignKey("accounts.id"), nullable=True,
    )
    account_destino_id = Column(
        Integer, ForeignKey("accounts.id"), nullable=True,
    )
    kind = Column(String(30), nullable=False)
    direction = Column(String(1), nullable=False)           # '+' | '-'
    amount = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(3), nullable=False)
    amount_eur = Column(Numeric(18, 4), nullable=True)
    fx_rate_to_eur = Column(Numeric(24, 12), nullable=True)
    fx_source = Column(String(20), nullable=True)  # statement|historical|manual
    fx_date = Column(Date, nullable=True)
    value_date = Column(Date, nullable=False)
    estado = Column(String(12), nullable=False, default="pendiente")
    merchant = Column(String(255), nullable=True)
    nota = Column(String(500), nullable=True)
    legacy = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, nullable=True,
                            onupdate=datetime.utcnow)

    event = relationship("NormalizedEvent")
    account = relationship("Account", foreign_keys=[account_id])
    account_destino = relationship("Account", foreign_keys=[account_destino_id])

    __table_args__ = (
        Index("ix_fm_value_date", "value_date"),
        Index("ix_fm_estado", "estado"),
        Index("ix_fm_kind", "kind"),
        Index("ix_fm_merchant", "merchant"),
        Index("ix_fm_estado_value_date", "estado", "value_date"),
        Index("ix_fm_account_value_date", "account_id", "value_date"),
    )


class MovementSource(Base):
    """Trazabilidad N:M: movimiento → archivos/filas que lo vieron."""

    __tablename__ = "movement_sources"

    movement_id = Column(
        Integer, ForeignKey("financial_movements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_row_id = Column(
        Integer, ForeignKey("raw_rows.id"),
        nullable=True,
    )
    match_type = Column(String(20), nullable=False)
    first_seen_en = Column(DateTime, default=datetime.utcnow)


class MovementLink(Base):
    """Enlace entre movimientos (transferencia interna, cash-leg de trade)."""

    __tablename__ = "movement_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movement_a = Column(
        Integer, ForeignKey("financial_movements.id"), nullable=False,
    )
    movement_b = Column(
        Integer, ForeignKey("financial_movements.id"), nullable=False,
    )
    link_type = Column(String(30), nullable=False)
    confianza = Column(String(10), default="alta")           # 'alta'|'media'|'baja'

    __table_args__ = (
        UniqueConstraint("movement_a", "movement_b", "link_type",
                         name="uq_movement_link"),
    )


class Classification(Base):
    """Decisión de clasificación sobre un movimiento (versión vigente)."""

    __tablename__ = "classifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movement_id = Column(
        Integer, ForeignKey("financial_movements.id", ondelete="CASCADE"),
        nullable=False,
    )
    categoria_id = Column(
        Integer, ForeignKey("categorias.id"), nullable=True,
    )
    subtipo = Column(String(50), nullable=True)
    origen = Column(String(10), nullable=False)   # rule|memory|llm|user|broker
    confianza = Column(Numeric(4, 3), nullable=True)
    explicacion = Column(Text, nullable=True)
    modelo = Column(String(60), nullable=True)
    prompt_version = Column(String(20), nullable=True)
    vigente = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    movement = relationship("FinancialMovement")
    categoria = relationship("Categoria")

    __table_args__ = (
        Index("ix_class_movement_vigente", "movement_id", "vigente"),
    )


class ClassificationRule(Base):
    """Regla determinista de clasificación definida por el usuario."""

    __tablename__ = "classification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prioridad = Column(Integer, default=100)
    campo = Column(String(30), nullable=False)
    operador = Column(String(20), nullable=False)
    valor = Column(String(255), nullable=False)
    set_categoria_id = Column(
        Integer, ForeignKey("categorias.id"), nullable=True,
    )
    set_subtipo = Column(String(50), nullable=True)
    set_merchant = Column(String(255), nullable=True)
    set_kind = Column(String(30), nullable=True)
    auto_aprobar = Column(Boolean, default=False)
    nombre = Column(String(255), nullable=True)
    descripcion = Column(Text, nullable=True)
    hit_count = Column(Integer, nullable=False, default=0)
    last_hit_at = Column(DateTime, nullable=True)
    activa = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    tags = relationship(
        "ClassificationRuleTag", back_populates="rule", cascade="all, delete-orphan"
    )


class ClassificationRuleTag(Base):
    """Etiquetas que una regla añade al movimiento cuando casa."""

    __tablename__ = "classification_rule_tags"

    rule_id = Column(
        Integer,
        ForeignKey("classification_rules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id = Column(
        Integer,
        ForeignKey("etiquetas.id", ondelete="CASCADE"),
        primary_key=True,
    )

    rule = relationship("ClassificationRule", back_populates="tags")
    etiqueta = relationship("Etiqueta")

    __table_args__ = (
        Index("ix_classification_rule_tags_tag_id", "tag_id"),
    )


class ClassificationMemory(Base):
    """Memoria de clasificaciones confirmadas por el usuario."""

    __tablename__ = "classification_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_key = Column(String(255), nullable=False)
    mcc_code = Column(String(4), nullable=True)
    broker_type = Column(String(40), nullable=True)
    categoria_id = Column(
        Integer, ForeignKey("categorias.id"), nullable=True,
    )
    subtipo = Column(String(50), nullable=True)
    merchant = Column(String(255), nullable=True)
    veces_aplicado = Column(Integer, default=0)
    veces_confirmado = Column(Integer, default=0)
    veces_corregido = Column(Integer, default=0)
    confianza = Column(Numeric(4, 3), default=0.80)
    origen = Column(String(10), default="user")
    embedding = Column(LargeBinary, nullable=True)          # fase 2 (optional)
    embedding_model = Column(String(60), nullable=True)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    ultimo_uso_en = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_cm_pattern", "pattern_key"),
        # Unicidad lógica también cuando mcc/broker_type son NULL.
        Index(
            "uq_cm_pattern_mcc_broker",
            "pattern_key",
            text("COALESCE(mcc_code, '')"),
            text("COALESCE(broker_type, '')"),
            unique=True,
        ),
    )


class DedupCandidate(Base):
    """Par de movimientos candidatos a ser duplicados (revisión manual)."""

    __tablename__ = "dedup_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movement_a = Column(
        Integer, ForeignKey("financial_movements.id"), nullable=False,
    )
    movement_b = Column(
        Integer, ForeignKey("financial_movements.id"), nullable=False,
    )
    score = Column(Numeric(5, 4), nullable=False)
    motivo = Column(String(255), nullable=True)
    estado = Column(String(15), default="pendiente")
    resuelto_en = Column(DateTime, nullable=True)
    resolved_by = Column(String(100), nullable=True)
    resolution_note = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("movement_a", "movement_b", name="uq_dedup_pair"),
    )


class ClassificationJob(Base):
    """Job de clasificación en background con logs."""

    __tablename__ = "classification_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), default="pending")  # pending | running | completed | cancelled | failed
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    rule_count = Column(Integer, default=0)
    memory_count = Column(Integer, default=0)
    llm_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    log_lines = Column(Text, default="[]")  # JSON array
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(String(500), nullable=True)


# ── ACTIVOS / CARTERA (v2) ────────────────────────────────────────────────────


class Asset(Base):
    """Activo financiero (acción, ETF, fondo, cripto). Reemplaza a Activo."""

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    isin = Column(String(12), nullable=True, unique=True)
    symbol = Column(String(20), nullable=False)
    yf_ticker = Column(String(30), nullable=True)
    nombre = Column(String(255), nullable=True)
    asset_class = Column(String(20), nullable=False)
    exchange = Column(String(100), nullable=True)
    moneda = Column(String(3), default="EUR")
    notas = Column(String(500), nullable=True)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_asset_symbol", "symbol"),
    )


class AssetTransaction(Base):
    """Operación sobre un activo (compra/venta/aporte/dividendo acción)."""

    __tablename__ = "asset_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False,
    )
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True
    )
    movement_id = Column(
        Integer, ForeignKey("financial_movements.id", ondelete="SET NULL"),
        nullable=True, unique=True,
    )
    tipo = Column(String(30), nullable=False)      # compra|venta|aporte|dividendo_accion
    shares = Column(Numeric(24, 10), nullable=False)
    price = Column(Numeric(18, 6), nullable=False)
    fee = Column(Numeric(18, 4), default=0)
    tax = Column(Numeric(18, 4), nullable=True)
    fx_rate = Column(Numeric(18, 8), nullable=True)
    lote_id = Column(String(64), nullable=True)
    moneda = Column(String(3), nullable=True)
    fecha = Column(Date, nullable=False)
    nota = Column(String(500), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset")

    __table_args__ = (
        Index("ix_at_asset_fecha", "asset_id", "fecha"),
    )


class PositionSnapshot(Base):
    """Posición calculada de un activo (cache)."""

    __tablename__ = "position_snapshots"

    asset_id = Column(
        Integer, ForeignKey("assets.id"), primary_key=True,
    )
    cantidad = Column(Numeric(24, 10), nullable=True)
    coste_total = Column(Numeric(18, 4), nullable=True)
    precio_medio = Column(Numeric(18, 6), nullable=True)
    invertido = Column(Numeric(18, 4), nullable=True)
    comisiones = Column(Numeric(18, 4), nullable=True)
    ganancia_realizada = Column(Numeric(18, 4), nullable=True)
    calculado_en = Column(DateTime, nullable=True)





# ── AUTENTICACIÓN (F0) ───────────────────────────────────────────────────────


class User(Base):
    """Usuario de la aplicación (single-user por ahora, rol admin)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="admin")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    disabled = Column(Boolean, nullable=False, default=False)

    sessions = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - evita exponer el hash
        return f"<User {self.email!r}>"


class Session(Base):
    """Sesión opaca revocable. Solo se guarda el SHA-256 del token."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_sessions_expires_at", "expires_at"),
    )


class LoginAttempt(Base):
    """Auditoría de intentos de login para rate limit y diagnóstico."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=True)
    ip = Column(String(45), nullable=True)
    ok = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_login_attempts_email_created", "email", "created_at"),
        Index("ix_login_attempts_ip_created", "ip", "created_at"),
    )


class AccountBalanceSnapshot(Base):
    """Conciliación de saldo declarado (extracto) vs calculado por la app."""

    __tablename__ = "account_balance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True
    )
    currency = Column(String(3), nullable=False, default="EUR")
    fecha = Column(Date, nullable=False)
    saldo_declarado = Column(Numeric(18, 4), nullable=True)
    saldo_calculado = Column(Numeric(18, 4), nullable=True)
    diferencia = Column(Numeric(18, 4), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")

    __table_args__ = (
        UniqueConstraint(
            "account_id", "currency", "fecha",
            name="uq_balance_snapshot_account_currency_fecha",
        ),
        Index(
            "ix_balance_snapshot_account_currency_fecha",
            "account_id", "currency", "fecha",
        ),
    )


class PortfolioSnapshot(Base):
    """Cabecera de un extracto de patrimonio/posiciones a una fecha."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True
    )
    snapshot_date = Column(Date, nullable=False)
    currency = Column(String(3), nullable=False, default="EUR")
    custody_ref = Column(String(80), nullable=True)
    cash_declared = Column(Numeric(18, 4), nullable=True)
    total_declared = Column(Numeric(18, 4), nullable=True)
    securities_value = Column(Numeric(18, 4), nullable=True)
    crypto_value = Column(Numeric(18, 4), nullable=True)
    metadata_json = Column(Text, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")

    __table_args__ = (
        UniqueConstraint(
            "account_id", "snapshot_date", "custody_ref",
            name="uq_portfolio_snapshot_account_date_custody",
        ),
        Index("ix_portfolio_snapshot_account_date", "account_id", "snapshot_date"),
    )


class PortfolioSnapshotPosition(Base):
    """Posición valorada dentro de un snapshot; nunca es una compra."""

    __tablename__ = "portfolio_snapshot_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    quantity = Column(Numeric(24, 10), nullable=False)
    price = Column(Numeric(18, 6), nullable=False)
    price_date = Column(Date, nullable=True)
    value = Column(Numeric(18, 4), nullable=False)
    cost_total = Column(Numeric(18, 4), nullable=True)
    pnl_declared = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(3), nullable=False, default="EUR")

    snapshot = relationship("PortfolioSnapshot")
    asset = relationship("Asset")

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "asset_id", name="uq_portfolio_snapshot_asset"
        ),
        Index("ix_psp_snapshot_asset", "snapshot_id", "asset_id"),
    )


class AssetOpeningPosition(Base):
    """Cantidad y coste de apertura, explícitos, derivados o estimados."""

    __tablename__ = "asset_opening_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    as_of_date = Column(Date, nullable=False)
    quantity = Column(Numeric(24, 10), nullable=False)
    cost_total = Column(Numeric(18, 4), nullable=True)
    cost_status = Column(String(20), nullable=False, default="unknown")
    source = Column(String(40), nullable=False, default="derived")
    source_file_id = Column(
        Integer, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True
    )
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")
    asset = relationship("Asset")

    __table_args__ = (
        UniqueConstraint(
            "account_id", "asset_id", "as_of_date",
            name="uq_asset_opening_account_asset_date",
        ),
        Index("ix_aop_account_asset_date", "account_id", "asset_id", "as_of_date"),
    )
