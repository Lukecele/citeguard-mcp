"""CiteGuard MCP — Anti-Hallucination Citation Verification & Literature MCP Server."""

__version__ = "0.1.4"

from .verifier import (
    verify_citation,
    audit_text,
    search_verified_literature,
    generate_bibtex,
    check_retraction,
)

__all__ = [
    "__version__",
    "verify_citation",
    "audit_text",
    "search_verified_literature",
    "generate_bibtex",
    "check_retraction",
]
