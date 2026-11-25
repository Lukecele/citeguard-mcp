---
name: citeguard-citation-guard
description: Verifies scientific citations (DOIs, PubMed PMIDs, arXiv IDs), detects LLM chimera metadata mismatches and retracted papers, audits Markdown/LaTeX/BibTeX drafts, and generates verified BibTeX using the citeguard-mcp MCP server. Use whenever writing, reviewing, or auditing scientific text, literature reviews, grant proposals, or bibliographies, or when asked to check citations, verify DOIs/PMIDs/arXiv IDs, detect fake references, or generate BibTeX.
when_to_use: |
  - User asks to write a scientific section, literature review, or technical report with citations
  - User asks to verify, audit, or fact-check DOIs, PubMed PMIDs, arXiv IDs, or a .bib / .tex / .md file
  - User asks to detect hallucinated, chimera, or retracted papers
  - User asks to format verified references into BibTeX
argument-hint: Provide a manuscript path, pasted text, BibTeX block, citation claim, or DOI/PMID/arXiv identifier to verify.
---

# CiteGuard Citation Guard

Protect scientific manuscripts, technical reports, grant proposals, and BibTeX files from fabricated identifiers, chimera citations (real DOIs paired with wrong titles, authors, or years), and silently retracted papers by routing all citation work through the **CiteGuard MCP** (`citeguard-mcp`) server.

## Required MCP Server

This skill teaches your agent when and how to invoke the **citeguard-mcp** MCP server tools:
- `search_verified_literature`
- `verify_citation`
- `audit_document_citations`
- `check_retraction`
- `generate_bibtex`

If the `citeguard-mcp` CLI is available locally instead of MCP tools, use the matching CLI subcommands (`citeguard search`, `citeguard verify`, `citeguard audit`, `citeguard retraction`, `citeguard bibtex`).

## Core Rules

1. **Never cite from memory alone.** Before inserting a new reference while drafting, call `search_verified_literature` to obtain registry-verified identifiers and metadata.
2. **Always check for chimera swaps.** When validating an existing citation that names a title, author, or year alongside a DOI, PMID, or arXiv ID, pass `claimed_title`, `claimed_author`, and `claimed_year` to `verify_citation`. Never trust HTTP 200 or syntax checks alone.
3. **Treat `RETRACTED` and `CHIMERA_MISMATCH` as hard blockers.** Never leave a retracted paper or mismatched identifier in a final bibliography without flagging or replacing it.
4. **Never fabricate fallback identifiers.** If no registry confirms a paper, mark it explicitly as `[UNVERIFIED — citation needed]` or find a real replacement via `search_verified_literature`.

## Decision Workflow

Choose the right tool for the task instead of calling tools redundantly:

1. **Drafting new text that needs citations**
   - Call `search_verified_literature(query=..., limit=5, source="all")`.
   - Select results where `is_retracted` is `false`, preferring peer-reviewed DOIs or verified arXiv preprints.
   - Insert the returned canonical citation and `bibtex` block directly.

2. **Checking a single reference or suspicious DOI/PMID/arXiv ID**
   - Call `verify_citation(identifier_or_query=..., claimed_title=..., claimed_author=..., claimed_year=...)`.
   - Inspect `verdict`:
     - `VERIFIED`: Safe to cite; use the returned canonical `record`, `bibtex`, and `apa`.
     - `CHIMERA_MISMATCH`: Stop and show the `issues` array (actual registry metadata vs. claimed metadata). Ask whether to correct the metadata or replace the source.
     - `RETRACTED`: Stop and warn the user using `retraction_notices`; search for a valid alternative if requested.
     - `FABRICATED_OR_UNRESOLVED`: Treat as invalid; search by title with `search_verified_literature` or remove the reference.

3. **Auditing a full draft, Markdown, LaTeX, or BibTeX file**
   - Read the target file (or take the pasted text) and call `audit_document_citations(text=...)`.
   - Report the overall `integrity_score` (`0–100%`) and counts (`verified_count`, `chimera_count`, `fabricated_count`, `retracted_count`).
   - List every non-`VERIFIED` entry with its exact issue and recommended fix.

4. **Fast retraction screening only**
   - When all metadata is already trusted and you only need retraction status on a DOI, call `check_retraction(doi=...)`.

5. **Batch BibTeX formatting**
   - When you already hold a trusted list of DOIs, `PMID:xxxx`, or `arXiv:xxxx.xxxxx` identifiers, call `generate_bibtex(identifiers=[...])` and surface any entries listed in `failed`.

## Output Format

When presenting audit or verification results to the user, return:
- **Integrity Summary**: total citations checked, verified count, and flagged count (`CHIMERA_MISMATCH`, `RETRACTED`, `FABRICATED_OR_UNRESOLVED`).
- **Actionable Table**: identifier, verdict, detected discrepancy or retraction notice, and corrected canonical BibTeX or replacement candidate.
- **Stop Boundaries**: if a manuscript contains unresolved or retracted citations, state clearly which lines require replacement before submission.

See `reference/registries-and-verdicts.md` for verdict semantics, registry coverage, and strictness thresholds.
