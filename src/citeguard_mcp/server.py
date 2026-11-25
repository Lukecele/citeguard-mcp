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

READ_ONLY_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "verify_citation",
        "title": "Verify Single Scientific Citation & Detect Chimera Hallucinations",
        "description": (
            "Read-only, idempotent verification of a single scientific citation (DOI, PubMed PMID, arXiv ID, "
            "or paper title) against Crossref, DataCite/Zenodo, PubMed (NCBI), OpenAlex, and arXiv (no API key required). "
            "Detects fabricated identifiers (HTTP 404 in all registries), chimera metadata mismatches (where a real DOI is "
            "paired with an incorrect or hallucinated title, author surname, or publication year), and retracted papers. "
            "Returns a JSON object with `verified` (bool), `verdict` ('VERIFIED', 'CHIMERA_MISMATCH', 'RETRACTED', or "
            "'FABRICATED_OR_UNRESOLVED'), `registry`, canonical `record` metadata, `checks`, `issues`, `bibtex`, and `apa`. "
            "When to use: use `verify_citation` to validate a single reference and its claimed title/author/year. "
            "Use `audit_document_citations` instead to scan a full document containing multiple citations; use "
            "`check_retraction` for a fast retraction-only check on a known DOI; use `search_verified_literature` "
            "to discover papers before writing citations."
        ),
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifier_or_query": {
                    "type": "string",
                    "description": (
                        "Identifier or bibliographic title to verify. Accepts a raw DOI or DOI URL "
                        "(e.g. '10.1038/s41586-021-03819-2' or 'https://doi.org/10.1038/s41586-021-03819-2', "
                        "case-insensitive, trailing punctuation stripped), a PubMed ID ('PMID:34265844' or digits), "
                        "an arXiv ID ('arXiv:1706.03762' with optional version 'v1'), or a full paper title string."
                    ),
                },
                "claimed_title": {
                    "type": "string",
                    "description": (
                        "Optional title claimed by the manuscript or LLM. Compared via normalized token similarity "
                        "(threshold >= 0.48) against the official registry title to detect chimera title swaps."
                    ),
                },
                "claimed_author": {
                    "type": "string",
                    "description": (
                        "Optional lead/first author surname claimed by the manuscript or LLM (e.g. 'Jumper'). "
                        "Checked case-insensitively against official registry author lists."
                    ),
                },
                "claimed_year": {
                    "type": "integer",
                    "description": (
                        "Optional 4-digit publication year claimed by the manuscript or LLM (e.g. 2021). "
                        "Flags a mismatch if it differs from the registry publication year by more than 1 year."
                    ),
                },
            },
            "required": ["identifier_or_query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "audit_document_citations",
        "title": "Audit All Citations in a Document (Markdown, LaTeX, BibTeX)",
        "description": (
            "Read-only, idempotent bulk citation auditor that extracts all inline DOIs, PubMed PMIDs, arXiv IDs, "
            "and BibTeX `@article{...}` entries from a Markdown, LaTeX, BibTeX, or draft text block and verifies each "
            "concurrently (up to 6 parallel workers) against Crossref, DataCite, PubMed, OpenAlex, and arXiv. "
            "Returns a JSON report containing `total_citations`, `verified_count`, `chimera_count` (real identifier paired "
            "with mismatched BibTeX title/author/year), `fabricated_count` (unresolvable identifiers), `retracted_count`, "
            "`integrity_score` (0.0 to 100.0 percentage), per-citation `results`, and a human-readable `summary`. "
            "If no citations are present, returns `total_citations: 0` and `integrity_score: 100.0`. "
            "When to use: use `audit_document_citations` to validate an entire manuscript, bibliography, or LLM response "
            "at once. For checking a single DOI/PMID/arXiv ID with specific claimed metadata, use `verify_citation` instead."
        ),
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Full Markdown, LaTeX, BibTeX (`.bib`), or plain-text document containing inline DOIs "
                        "('10.xxxx/...'), PMIDs ('PMID:12345678'), arXiv IDs ('arXiv:2103.00020'), or BibTeX entries."
                    ),
                }
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_verified_literature",
        "title": "Search Registry-Verified Scientific Literature",
        "description": (
            "Read-only, idempotent literature discovery tool that queries OpenAlex, Crossref, PubMed (NCBI), and arXiv "
            "(no API key required) to find real, peer-reviewed articles and preprints matching a scientific query. "
            "Returns a JSON object with `query`, `count`, and `results` (ordered by registry relevance), where each item "
            "includes `registry`, `title`, `authors`, `year`, `journal`, `doi`, `url`, `open_access_url`, `citation_count`, "
            "`is_retracted`, plus ready-to-paste `bibtex` and `apa` strings. Network or upstream timeouts degrade gracefully "
            "by returning results from available registries. "
            "When to use: call `search_verified_literature` BEFORE writing citations on a topic so every cited paper has a "
            "verified identifier. Do not use this tool to validate an existing DOI/PMID (use `verify_citation` instead) or "
            "to format known identifiers into BibTeX (use `generate_bibtex` instead)."
        ),
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Scientific keywords, research question, or paper title to search (non-empty string).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of verified papers to return (clamped to range 1-20, default: 5).",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "source": {
                    "type": "string",
                    "enum": ["all", "openalex", "crossref", "pubmed", "arxiv"],
                    "description": (
                        "Registry source to query: 'all' (queries OpenAlex/Crossref first, then supplements with PubMed "
                        "and arXiv), 'openalex', 'crossref', 'pubmed', or 'arxiv'. Default: 'all'."
                    ),
                    "default": "all",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_bibtex",
        "title": "Generate Normalized BibTeX from DOIs, PMIDs, or arXiv IDs",
        "description": (
            "Read-only, idempotent batch formatter that resolves an array of DOIs, PubMed PMIDs, or arXiv IDs in input "
            "order against Crossref, DataCite, PubMed, and arXiv and formats each into a deterministic `@article{...}` "
            "BibTeX entry (`authorSurnameYearFirstword` key). Partial failures never abort the batch: unresolvable "
            "identifiers are omitted from the `bibtex` string and listed in the `failed` array. Returns a JSON object "
            "with `resolved_count` (int), `failed` (array of unresolved identifier strings), and `bibtex` (newline-separated "
            "BibTeX blocks). "
            "When to use: use `generate_bibtex` when you already have one or more known DOIs/PMIDs/arXiv IDs and only need "
            "clean BibTeX output. Use `verify_citation` instead if you need chimera title/author/year mismatch checking."
        ),
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of identifiers to convert to BibTeX: DOIs (e.g. '10.1038/s41586-021-03819-2'), "
                        "PubMed IDs (e.g. 'PMID:34265844'), or arXiv IDs (e.g. 'arXiv:1706.03762')."
                    ),
                }
            },
            "required": ["identifiers"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_retraction",
        "title": "Check DOI Retraction Status in Crossref & OpenAlex",
        "description": (
            "Read-only, idempotent retraction scanner that queries both Crossref (`update-to` retraction/withdrawal notices "
            "and `is-retracted-by` relations) and OpenAlex (`is_retracted` flag) for a given DOI. A DOI is flagged as "
            "retracted if either Crossref or OpenAlex reports a retraction. Returns a JSON object with `doi` (normalized), "
            "`exists` (bool), `title` (string, if found), `is_retracted` (bool), `status` ('RETRACTED', 'ACTIVE', or "
            "'NOT_FOUND' when the DOI does not exist in either registry), `notices` (array of notice labels), and `message`. "
            "When to use: use `check_retraction` for a fast, targeted retraction check on a specific DOI without full "
            "BibTeX generation or chimera metadata comparison. Use `verify_citation` instead for full citation verification, "
            "or `audit_document_citations` to scan an entire document."
        ),
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "doi": {
                    "type": "string",
                    "description": (
                        "Registered DOI to check for retraction status (e.g. '10.1016/S0140-6736(97)11096-0' or full "
                        "'https://doi.org/...' URL; case-insensitive, prefix and trailing punctuation stripped automatically)."
                    ),
                }
            },
            "required": ["doi"],
            "additionalProperties": False,
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
