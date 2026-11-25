# Registries, Matching Thresholds, and Verdict Reference

## Authoritative Registries Queried

`citeguard-mcp` queries five public scholarly registries without requiring API keys:

| Registry | Identifiers Covered | Primary Capabilities |
| :--- | :--- | :--- |
| **Crossref** | `10.xxxx/...` DOIs | Canonical titles, authors, years, journal metadata, and `update-to` / `is-retracted-by` retraction notices |
| **DataCite** | Zenodo & dataset DOIs | Dataset, software, and preprint DOI resolution when not indexed in Crossref |
| **PubMed (NCBI E-utilities)** | `PMID:xxxxxxxx` | Biomedical citation metadata, authors, journals, and linked DOIs |
| **OpenAlex** | DOIs & keyword queries | Citation counts, open-access PDF links, and `is_retracted` status |
| **arXiv** | `arXiv:YYMM.NNNNN` | Preprint titles, authors, publication dates, and BibTeX generation |

## Verdict Semantics

- **`VERIFIED`**: Identifier resolves in at least one authoritative registry, no retraction notice is active, and any provided `claimed_title`, `claimed_author`, or `claimed_year` matches canonical metadata.
- **`CHIMERA_MISMATCH`**: Identifier exists in a registry, **but** one or more claimed fields disagree:
  - Title token similarity falls below `0.48`
  - Claimed first/lead author surname is absent from the registry author list
  - Claimed publication year differs from the canonical year by more than `1` year
- **`RETRACTED`**: Crossref reports a retraction/withdrawal notice (`update-to` / `is-retracted-by`) or OpenAlex flags `is_retracted: true`.
- **`FABRICATED_OR_UNRESOLVED`**: Identifier returns HTTP 404 / empty match across all applicable registries.

## Limitations

- Public registry rate limits or transient network timeouts may prevent verification of a subset of citations during bulk audits; always check `failed` or `issues` fields before assuming completeness.
- Verification confirms bibliographic existence, metadata consistency, and retraction status; it does not evaluate whether a study's experimental methodology supports the user's scientific argument.
