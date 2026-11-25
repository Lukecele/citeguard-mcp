"""Model Context Protocol (MCP) JSON-RPC 2.0 Server over stdio (zero external dependencies)."""

from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__
from .verifier import (
    audit_text,
    check_retraction,
    generate_bibtex,
    search_verified_literature,
    verify_citation,
)

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "verify_citation",
        "description": (
            "Verify a scientific citation (DOI, PubMed PMID, arXiv ID, or bibliographic query) against "
            "Crossref, DataCite/Zenodo, PubMed, OpenAlex, and arXiv. Detects hallucinated/non-existent "
            "identifiers, chimera metadata mismatches (real DOI paired with wrong title/author/year), "
            "and retracted papers. Returns canonical metadata, BibTeX, and APA citation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifier_or_query": {
                    "type": "string",
                    "description": "DOI (e.g. '10.1038/s41586-021-03819-2'), PMID (e.g. 'PMID:34265844'), arXiv ID (e.g. 'arXiv:1706.03762'), or paper title.",
                },
                "claimed_title": {
                    "type": "string",
                    "description": "Optional paper title claimed by the document or LLM to check for chimera title mismatch.",
                },
                "claimed_author": {
                    "type": "string",
                    "description": "Optional first/lead author surname claimed by the document or LLM.",
                },
                "claimed_year": {
                    "type": "integer",
                    "description": "Optional publication year claimed by the document or LLM.",
                },
            },
            "required": ["identifier_or_query"],
        },
    },
    {
        "name": "audit_document_citations",
        "description": (
            "Audit all citations (DOIs, PMIDs, arXiv IDs, and BibTeX entries) inside a Markdown, LaTeX, "
            "BibTeX, or LLM-generated text block. Concurrently verifies every reference and computes a "
            "Citation Integrity Score (0-100%) flagging fabricated, chimera, or retracted references."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Full text (Markdown, LaTeX, BibTeX, or draft response) containing citations to audit.",
                }
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_verified_literature",
        "description": (
            "Search OpenAlex, Crossref, PubMed (NCBI), and arXiv for real, registry-verified scientific "
            "papers. Use this tool BEFORE citing literature so you only cite 100% real papers with "
            "verified DOIs, years, authors, and ready-to-paste BibTeX/APA references."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Scientific topic, keywords, or paper title to search.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of verified papers to return (1-20, default 5).",
                    "default": 5,
                },
                "source": {
                    "type": "string",
                    "enum": ["all", "openalex", "pubmed", "arxiv"],
                    "description": "Registry source to query (default: 'all').",
                    "default": "all",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_bibtex",
        "description": "Convert a list of DOIs, PubMed PMIDs, or arXiv IDs into normalized, verified BibTeX entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of DOIs, PMIDs (e.g. 'PMID:34265844'), or arXiv IDs (e.g. 'arXiv:1706.03762').",
                }
            },
            "required": ["identifiers"],
        },
    },
    {
        "name": "check_retraction",
        "description": "Check whether a DOI has been retracted or has retraction notices in Crossref and OpenAlex.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doi": {
                    "type": "string",
                    "description": "DOI to check for retraction status (e.g. '10.1016/S0140-6736(97)11096-0').",
                }
            },
            "required": ["doi"],
        },
    },
]


def handle_mcp_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        client_proto = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "citeguard-mcp",
                    "version": __version__,
                },
            },
        }

    if method.startswith("notifications/"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "verify_citation":
                out = verify_citation(
                    args["identifier_or_query"],
                    claimed_title=args.get("claimed_title"),
                    claimed_author=args.get("claimed_author"),
                    claimed_year=args.get("claimed_year"),
                )
            elif name == "audit_document_citations":
                out = audit_text(args["text"])
            elif name == "search_verified_literature":
                out = search_verified_literature(
                    args["query"],
                    limit=args.get("limit", 5),
                    source=args.get("source", "all"),
                )
            elif name == "generate_bibtex":
                out = generate_bibtex(args.get("identifiers", []))
            elif name == "check_retraction":
                out = check_retraction(args["doi"])
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(out, indent=2, ensure_ascii=False)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error executing {name}: {exc}"}],
                    "isError": True,
                },
            }

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def run_stdio_server() -> None:
    """Run the MCP JSON-RPC 2.0 server over standard input/output."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_mcp_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
