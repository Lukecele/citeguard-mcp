"""Rich Terminal CLI & MCP Server entrypoint for CiteGuard (`citeguard` / `citeguard-mcp`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .server import run_stdio_server
from .verifier import (
    audit_text,
    check_retraction,
    generate_bibtex,
    search_verified_literature,
    verify_citation,
)

# ANSI Styling
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


def _banner() -> str:
    return (
        f"{CYAN}{BOLD}╭──────────────────────────────────────────────────────────────────────────╮{RESET}\n"
        f"{CYAN}{BOLD}│{RESET}  🛡️  {BOLD}CiteGuard MCP v{__version__}{RESET} — Anti-Hallucination Citation & DOI Verifier  {CYAN}{BOLD}│{RESET}\n"
        f"{CYAN}{BOLD}│{RESET}  {DIM}Crossref · DataCite/Zenodo · PubMed (NCBI) · OpenAlex · arXiv{RESET}           {CYAN}{BOLD}│{RESET}\n"
        f"{CYAN}{BOLD}╰──────────────────────────────────────────────────────────────────────────╯{RESET}"
    )


def _badge(verdict: str) -> str:
    if verdict == "VERIFIED":
        return f"{GREEN}{BOLD}✔ VERIFIED{RESET}"
    if verdict == "CHIMERA_MISMATCH":
        return f"{YELLOW}{BOLD}⚠ CHIMERA MISMATCH{RESET}"
    if verdict == "RETRACTED":
        return f"{MAGENTA}{BOLD}🚨 RETRACTED{RESET}"
    if verdict == "REGISTRY_UNAVAILABLE":
        return f"{YELLOW}{BOLD}⏳ REGISTRY UNAVAILABLE (5xx/429/Timeout){RESET}"
    return f"{RED}{BOLD}✘ FABRICATED / 404{RESET}"


def _print_verify_result(res: dict) -> None:
    print(_banner())
    print(f"\n  Status   : {_badge(res['verdict'])}")
    rec = res.get("record")
    if rec:
        print(f"  Registry : {CYAN}{res.get('registry')}{RESET}")
        print(f"  Title    : {BOLD}{rec.get('title')}{RESET}")
        authors = ", ".join(rec.get("authors", [])[:5])
        if len(rec.get("authors", [])) > 5:
            authors += " et al."
        print(f"  Authors  : {authors}")
        print(f"  Venue    : {rec.get('journal')} ({rec.get('year')})")
        if rec.get("doi"):
            print(f"  DOI      : https://doi.org/{rec['doi']}")
        elif rec.get("url"):
            print(f"  URL      : {rec['url']}")
    for iss in res.get("issues", []):
        print(f"  {RED}▸ {iss}{RESET}")
    if res.get("bibtex"):
        print(f"\n  {DIM}── Verified BibTeX ──{RESET}")
        for line in res["bibtex"].splitlines():
            print(f"  {CYAN}{line}{RESET}")
    print()


def _print_audit_report(report: dict) -> None:
    print(_banner())
    total = report["total_citations"]
    if total == 0:
        print(f"\n  {YELLOW}No citations (DOIs, PMIDs, arXiv IDs, or BibTeX entries) detected.{RESET}\n")
        return

    score = report["integrity_score"]
    score_color = GREEN if score == 100.0 else (YELLOW if score >= 75.0 else RED)
    print(
        f"\n  {BOLD}Citation Integrity Score:{RESET} {score_color}{BOLD}{score:.1f}%{RESET}  "
        f"({GREEN}{report['verified_count']} Verified{RESET} · "
        f"{YELLOW}{report['chimera_count']} Chimera{RESET} · "
        f"{RED}{report['fabricated_count']} Fabricated/404{RESET} · "
        f"{MAGENTA}{report['retracted_count']} Retracted{RESET})\n"
    )
    print(f"  {DIM}{'─' * 74}{RESET}")
    for idx, r in enumerate(report["results"], 1):
        rec = r.get("record") or {}
        title = rec.get("title") or r.get("query", "")
        if len(title) > 64:
            title = title[:61] + "..."
        reg = f" [{r['registry']}]" if r.get("registry") else ""
        print(f"  {BOLD}#{idx:02d}{RESET} {_badge(r['verdict'])}{DIM}{reg}{RESET} — {BOLD}{r.get('source_label')}{RESET}")
        if rec.get("title"):
            yr = rec.get("year") or "n.d."
            auth = (rec.get("authors") or ["Unknown"])[0]
            print(f"      {DIM}{auth} ({yr}) · {title}{RESET}")
        for iss in r.get("issues", []):
            print(f"      {RED}↳ {iss}{RESET}")
    print(f"  {DIM}{'─' * 74}{RESET}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="citeguard",
        description="CiteGuard MCP — Anti-Hallucination Citation Verification & Scientific Literature MCP Server.",
    )
    parser.add_argument("--version", action="version", version=f"citeguard-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    # 1. serve (default when run as MCP server)
    sub.add_parser("serve", help="Run the Model Context Protocol (MCP) JSON-RPC 2.0 server over stdio.")

    # 2. verify
    p_ver = sub.add_parser("verify", help="Verify a single DOI, PMID, arXiv ID, or citation string.")
    p_ver.add_argument("identifier", help="DOI, PMID:xxxx, arXiv:xxxx.xxxxx, or paper title.")
    p_ver.add_argument("--title", help="Claimed title to verify against chimera hallucinations.")
    p_ver.add_argument("--author", help="Claimed author surname to verify.")
    p_ver.add_argument("--year", type=int, help="Claimed publication year to verify.")
    p_ver.add_argument("--json", action="store_true", help="Output raw JSON.")

    # 3. audit
    p_aud = sub.add_parser("audit", help="Audit all citations in a Markdown, LaTeX, BibTeX, or text file.")
    p_aud.add_argument("file", nargs="?", help="Path to .md, .tex, .bib, or .txt file (or '-' for stdin).")
    p_aud.add_argument("--text", help="Direct text string to audit.")
    p_aud.add_argument("--strict", action="store_true", help="Exit with code 1 if any unverified citation is found.")
    p_aud.add_argument(
        "--fail-on-network-error",
        action="store_true",
        help="With --strict, also exit 1 if upstream registries were unreachable (REGISTRY_UNAVAILABLE).",
    )
    p_aud.add_argument("--json", action="store_true", help="Output raw JSON.")

    # 4. search
    p_src = sub.add_parser("search", help="Search OpenAlex, PubMed, Crossref & arXiv for verified literature.")
    p_src.add_argument("query", help="Search query.")
    p_src.add_argument("--limit", type=int, default=5, help="Max results (default: 5).")
    p_src.add_argument("--source", choices=["all", "openalex", "pubmed", "arxiv"], default="all")
    p_src.add_argument("--json", action="store_true", help="Output raw JSON.")

    # 5. bibtex
    p_bib = sub.add_parser("bibtex", help="Generate verified BibTeX entries for one or more DOIs/PMIDs/arXiv IDs.")
    p_bib.add_argument("identifiers", nargs="+", help="One or more DOIs, PMIDs, or arXiv IDs.")

    # 6. retraction
    p_ret = sub.add_parser("retraction", help="Check if a DOI has been retracted in Crossref or OpenAlex.")
    p_ret.add_argument("doi", help="DOI to check.")
    p_ret.add_argument("--json", action="store_true", help="Output raw JSON.")

    args = parser.parse_args(argv)

    # If invoked with no subcommand (e.g. `uvx citeguard-mcp` by Claude Desktop / Cursor / Antigravity):
    if args.command in (None, "serve"):
        if args.command is None and sys.stdin.isatty():
            parser.print_help()
            return 0
        run_stdio_server()
        return 0

    if args.command == "verify":
        res = verify_citation(
            args.identifier,
            claimed_title=args.title,
            claimed_author=args.author,
            claimed_year=args.year,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            _print_verify_result(res)
        return 0 if res["verified"] else 1

    if args.command == "audit":
        if args.text:
            content = args.text
        elif args.file and args.file != "-":
            content = Path(args.file).read_text(encoding="utf-8", errors="replace")
        else:
            content = sys.stdin.read()
        report = audit_text(content)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _print_audit_report(report)
        if args.strict and (
            report["chimera_count"] > 0
            or report["fabricated_count"] > 0
            or report["retracted_count"] > 0
            or (args.fail_on_network_error and report.get("unavailable_count", 0) > 0)
        ):
            return 1
        return 0

    if args.command == "search":
        res = search_verified_literature(args.query, limit=args.limit, source=args.source)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(_banner())
            print(f"\n  Found {BOLD}{res['count']}{RESET} verified papers for '{CYAN}{res['query']}{RESET}':\n")
            for idx, r in enumerate(res["results"], 1):
                print(f"  {BOLD}[{idx}] {r['title']}{RESET}")
                print(f"      {DIM}{r['apa']}{RESET}\n")
        return 0

    if args.command == "bibtex":
        res = generate_bibtex(args.identifiers)
        print(res["bibtex"])
        return 0 if not res["failed"] else 1

    if args.command == "retraction":
        res = check_retraction(args.doi)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(_banner())
            color = MAGENTA if res["is_retracted"] else GREEN
            print(f"\n  {color}{BOLD}{res['status']}{RESET}: {res['message']}\n")
        return 1 if res["is_retracted"] else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
