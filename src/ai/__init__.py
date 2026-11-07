"""Capa de IA de financial-tools (fases F3/F4).

Piezas principales:

- ``OpenCodeGoClient``: cliente HTTP directo para OpenCode Go.
- ``JevProvider``: decisor tipado contra TypeSafe/Jev.
- ``DecisionOrchestrator``: umbrales, cache y ``DecisionResult``.
- ``DocumentIntakeAgent``: orquestador documental determinista (esqueleto).
"""

from .decision import DecisionOrchestrator, DecisionProvider, Thresholds
from .document_agent import (
    TOOL_ALLOWLIST,
    AgentTool,
    DocumentIntakeAgent,
    FileKind,
    FileProbe,
    probe_file,
    reconcile_balance,
    validate_envelope,
)
from .jev import (
    JevAnswer,
    JevAuthError,
    JevError,
    JevProvider,
    JevRateLimitError,
    JevResponseError,
    JevResult,
    JevServerError,
)
from .opencode_go import (
    OpenCodeAuthError,
    OpenCodeGoClient,
    OpenCodeGoError,
    OpenCodeModelError,
    OpenCodeQuotaError,
    OpenCodeRateLimitError,
    OpenCodeResponseError,
    OpenCodeServerError,
    api_family_for_model,
)
from .schemas import (
    Allowance,
    DecisionQuestion,
    DecisionResult,
    DocumentEnvelope,
    DocumentIssue,
    DocumentType,
    DocumentUnit,
    LLMResult,
    QuestionType,
    Usage,
)

__all__ = [
    "AgentTool",
    "Allowance",
    "DecisionOrchestrator",
    "DecisionProvider",
    "DecisionQuestion",
    "DecisionResult",
    "DocumentEnvelope",
    "DocumentIntakeAgent",
    "DocumentIssue",
    "DocumentType",
    "DocumentUnit",
    "FileKind",
    "FileProbe",
    "JevAnswer",
    "JevAuthError",
    "JevError",
    "JevProvider",
    "JevRateLimitError",
    "JevResponseError",
    "JevResult",
    "JevServerError",
    "LLMResult",
    "OpenCodeAuthError",
    "OpenCodeGoClient",
    "OpenCodeGoError",
    "OpenCodeModelError",
    "OpenCodeQuotaError",
    "OpenCodeRateLimitError",
    "OpenCodeResponseError",
    "OpenCodeServerError",
    "QuestionType",
    "Thresholds",
    "TOOL_ALLOWLIST",
    "Usage",
    "api_family_for_model",
    "probe_file",
    "reconcile_balance",
    "validate_envelope",
]
