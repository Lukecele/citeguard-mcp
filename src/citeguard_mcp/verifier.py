"""Core verification, anti-hallucination chimera detector, retraction scanner, and multi-registry search."""

from __future__ import annotations

import concurrent.futures
import html
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

USER_AGENT = "CiteGuard-MCP/0.1.0 (https://github.com/Lukecele/citeguard-mcp; mailto:luca.celebrano1@gmail.com)"
DEFAULT_TIMEOUT = 10

DOI_REGEX = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
PMID_REGEX = re.compile(r"\bPMID:\s*(\d{4,9})\b", re.IGNORECASE)
ARXIV_REGEX = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
BIBTEX_ENTRY_REGEX = re.compile(r"@(\w+)\s*\{\s*([^,]+),([\s\S]*?)\n\}", re.MULTILINE)


def _http_get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    return None


def _http_get_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


def _normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return " ".join(text.split())


def _title_similarity(claimed: str, actual: str) -> float:
    c_norm = _normalize_text(claimed)
    a_norm = _normalize_text(actual)
    if not c_norm or not a_norm:
        return 1.0
    if c_norm in a_norm or a_norm in c_norm:
        return 1.0
    stop = {"the", "a", "an", "of", "in", "on", "for", "and", "to", "with", "by", "from", "at", "via"}
    c_tokens = {t for t in c_norm.split() if len(t) > 2 and t not in stop}
    a_tokens = {t for t in a_norm.split() if len(t) > 2 and t not in stop}
    if not c_tokens or not a_tokens:
        return 1.0
    overlap = len(c_tokens & a_tokens)
    jaccard = overlap / len(c_tokens | a_tokens)
    recall = overlap / min(len(c_tokens), len(a_tokens))
    return round(max(jaccard, recall * 0.9), 3)


def _clean_doi(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^doi:\s*", "", s, flags=re.IGNORECASE)
    return s.rstrip(".,;)]}>\"'")


def _format_bibtex(record: dict[str, Any]) -> str:
    authors = record.get("authors") or ["Unknown"]
    first_raw = authors[0]
    surname_part = first_raw.split(",")[0] if "," in first_raw else first_raw.split()[-1]
    first_surname = _normalize_text(surname_part).replace(" ", "") or "ref"
    year = str(record.get("year") or "nd")
    title = record.get("title") or "Untitled"
    first_word = next((w for w in _normalize_text(title).split() if len(w) > 3), "paper")
    cite_key = f"{first_surname}{year}{first_word}"
    author_str = " and ".join(authors)
    lines = [
        f"@article{{{cite_key},",
        f"  author = {{{author_str}}},",
        f"  title = {{{title}}},",
    ]
    if record.get("journal"):
        lines.append(f"  journal = {{{record['journal']}}},")
    if record.get("year"):
        lines.append(f"  year = {{{record['year']}}},")
    if record.get("doi"):
        lines.append(f"  doi = {{{record['doi']}}},")
        lines.append(f"  url = {{https://doi.org/{record['doi']}}},")
    elif record.get("url"):
        lines.append(f"  url = {{{record['url']}}},")
    if record.get("pmid"):
        lines.append(f"  pmid = {{{record['pmid']}}},")
    if record.get("arxiv_id"):
        lines.append(f"  eprint = {{{record['arxiv_id']}}},")
        lines.append("  archivePrefix = {arXiv},")
    lines.append("}")
    return "\n".join(lines)


def _format_apa(record: dict[str, Any]) -> str:
    authors = record.get("authors") or ["Unknown"]
    if len(authors) > 6:
        auth_txt = ", ".join(authors[:6]) + ", et al."
    else:
        auth_txt = ", ".join(authors)
    year = record.get("year") or "n.d."
    title = record.get("title") or "Untitled"
    journal = record.get("journal") or record.get("source") or ""
    doi = record.get("doi")
    tail = f" https://doi.org/{doi}" if doi else (f" {record.get('url')}" if record.get("url") else "")
    j_part = f" {journal}." if journal else ""
    return f"{auth_txt} ({year}). {title}.{j_part}{tail}".strip()


def _lookup_crossref_doi(doi: str) -> dict[str, Any] | None:
    encoded = urllib.parse.quote(doi, safe="")
    data = _http_get_json(f"https://api.crossref.org/works/{encoded}")
    if not data or "message" not in data:
        return None
    msg = data["message"]
    titles = msg.get("title") or []
    title = html.unescape(re.sub(r"<[^>]+>", "", titles[0])).strip() if titles else ""
    authors = []
    for a in msg.get("author", []):
        given = a.get("given", "").strip()
        family = a.get("family", "").strip()
        name = f"{family}, {given}" if (family and given) else (family or given or a.get("name", ""))
        if name:
            authors.append(name)
    year = None
    for date_field in ("published-print", "published-online", "issued", "created"):
        parts = msg.get(date_field, {}).get("date-parts", [[]])
        if parts and parts[0]:
            year = int(parts[0][0])
            break
    containers = msg.get("container-title") or []
    journal = html.unescape(containers[0]).strip() if containers else msg.get("publisher", "")
    is_retracted = False
    retraction_details = []
    for upd in msg.get("update-to", []):
        utype = (upd.get("type") or "").lower()
        if "retract" in utype or "withdrawal" in utype:
            is_retracted = True
            retraction_details.append(upd.get("label") or utype)
    for rel_key in ("is-retracted-by", "retracts"):
        if msg.get("relation", {}).get(rel_key):
            is_retracted = True
            retraction_details.append(rel_key)
    if title.lower().startswith("retracted:") or "retracted article" in title.lower():
        is_retracted = True
    return {
        "registry": "Crossref",
        "doi": msg.get("DOI", doi),
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "url": f"https://doi.org/{msg.get('DOI', doi)}",
        "citation_count": msg.get("is-referenced-by-count", 0),
        "is_retracted": is_retracted,
        "retraction_notices": retraction_details,
    }


def _lookup_datacite_doi(doi: str) -> dict[str, Any] | None:
    encoded = urllib.parse.quote(doi, safe="")
    data = _http_get_json(f"https://api.datacite.org/dois/{encoded}")
    if not data or "data" not in data:
        return None
    attrs = data["data"].get("attributes", {})
    titles = attrs.get("titles") or []
    title = titles[0].get("title", "").strip() if titles else ""
    authors = []
    for c in attrs.get("creators", []):
        name = c.get("name") or f"{c.get('familyName', '')}, {c.get('givenName', '')}".strip(", ")
        if name:
            authors.append(name)
    year = attrs.get("publicationYear")
    return {
        "registry": "DataCite",
        "doi": attrs.get("doi", doi),
        "title": title,
        "authors": authors,
        "year": int(year) if year else None,
        "journal": attrs.get("publisher", "DataCite / Zenodo"),
        "url": attrs.get("url") or f"https://doi.org/{doi}",
        "citation_count": attrs.get("citationCount", 0),
        "is_retracted": False,
        "retraction_notices": [],
    }


def _lookup_pubmed_pmid(pmid: str) -> dict[str, Any] | None:
    clean_id = re.sub(r"\D", "", pmid)
    if not clean_id:
        return None
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={clean_id}&retmode=json"
    data = _http_get_json(url)
    if not data or "result" not in data or clean_id not in data["result"]:
        return None
    item = data["result"][clean_id]
    if "error" in item or not item.get("title"):
        return None
    title = html.unescape(re.sub(r"<[^>]+>", "", item.get("title", ""))).rstrip(".")
    authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
    pubdate = item.get("pubdate", "")
    ym = re.search(r"\b(19|20)\d{2}\b", pubdate)
    year = int(ym.group(0)) if ym else None
    doi = None
    for aid in item.get("articleids", []):
        if aid.get("idtype") == "doi":
            doi = aid.get("value")
            break
    pubtypes = [pt.lower() for pt in item.get("pubtype", [])]
    is_retracted = any("retracted" in pt or "retraction" in pt for pt in pubtypes)
    return {
        "registry": "PubMed (NCBI)",
        "pmid": clean_id,
        "doi": doi,
        "title": title,
        "authors": authors,
        "year": year,
        "journal": item.get("fulljournalname") or item.get("source", "PubMed"),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{clean_id}/",
        "is_retracted": is_retracted,
        "retraction_notices": ["PubMed Retracted Publication"] if is_retracted else [],
    }


def _lookup_arxiv_id(arxiv_id: str) -> dict[str, Any] | None:
    clean_id = re.sub(r"^arXiv:\s*", "", arxiv_id.strip(), flags=re.IGNORECASE)
    xml_txt = _http_get_text(f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(clean_id)}")
    if not xml_txt:
        return None
    try:
        root = ET.fromstring(xml_txt)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None
        title_el = entry.find("atom:title", ns)
        if title_el is None or not title_el.text or title_el.text.strip() == "Error":
            return None
        title = " ".join(title_el.text.strip().split())
        authors = []
        for a in entry.findall("atom:author", ns):
            n_el = a.find("atom:name", ns)
            if n_el is not None and n_el.text:
                authors.append(n_el.text.strip())
        pub_el = entry.find("atom:published", ns)
        year = int(pub_el.text[:4]) if (pub_el is not None and pub_el.text and len(pub_el.text) >= 4) else None
        doi_el = entry.find("arxiv:doi", ns)
        doi = doi_el.text.strip() if (doi_el is not None and doi_el.text) else None
        return {
            "registry": "arXiv",
            "arxiv_id": clean_id,
            "doi": doi,
            "title": title,
            "authors": authors,
            "year": year,
            "journal": f"arXiv:{clean_id}",
            "url": f"https://arxiv.org/abs/{clean_id}",
            "pdf_url": f"https://arxiv.org/pdf/{clean_id}.pdf",
            "is_retracted": False,
            "retraction_notices": [],
        }
    except Exception:
        return None


def check_retraction(doi: str) -> dict[str, Any]:
    """Check if a DOI has been retracted or issued an editorial expression of concern via Crossref & OpenAlex."""
    clean = _clean_doi(doi)
    cr = _lookup_crossref_doi(clean)
    oa = _http_get_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(clean, safe='')}")
    oa_retracted = bool(oa and oa.get("is_retracted"))
    cr_retracted = bool(cr and cr.get("is_retracted"))
    is_retracted = oa_retracted or cr_retracted
    if not cr and not oa:
        return {
            "doi": clean,
            "exists": False,
            "is_retracted": False,
            "status": "NOT_FOUND",
            "message": f"DOI {clean} was not found in Crossref or OpenAlex.",
        }
    title = (cr and cr.get("title")) or (oa and oa.get("title")) or "Unknown"
    notices = (cr and cr.get("retraction_notices")) or []
    if oa_retracted and "OpenAlex is_retracted=True" not in notices:
        notices.append("OpenAlex is_retracted=True")
    return {
        "doi": clean,
        "exists": True,
        "title": title,
        "is_retracted": is_retracted,
        "status": "RETRACTED" if is_retracted else "ACTIVE",
        "notices": notices,
        "message": (
            f"ALERT: '{title}' (DOI: {clean}) is flagged as RETRACTED ({', '.join(notices)})."
            if is_retracted
            else f"VERIFIED ACTIVE: '{title}' (DOI: {clean}) has no retraction flags in Crossref or OpenAlex."
        ),
    }


def verify_citation(
    identifier_or_query: str,
    claimed_title: str | None = None,
    claimed_author: str | None = None,
    claimed_year: int | str | None = None,
) -> dict[str, Any]:
    """
    Verify a scientific citation (DOI, PMID, arXiv ID, or title query) against official registries
    and detect fabricated identifiers, chimera metadata hallucinations, and retracted papers.
    """
    raw = identifier_or_query.strip()
    record: dict[str, Any] | None = None
    id_type = "query"

    doi_m = DOI_REGEX.search(raw)
    pmid_m = PMID_REGEX.search(raw)
    arxiv_m = ARXIV_REGEX.search(raw)

    if doi_m:
        id_type = "doi"
        clean = _clean_doi(doi_m.group(1))
        record = _lookup_crossref_doi(clean) or _lookup_datacite_doi(clean)
        if record and record.get("registry") == "Crossref" and not record.get("is_retracted"):
            oa = _http_get_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(clean, safe='')}")
            if oa and oa.get("is_retracted"):
                record["is_retracted"] = True
                record.setdefault("retraction_notices", []).append("OpenAlex is_retracted=True")
    elif pmid_m or (raw.isdigit() and 5 <= len(raw) <= 9):
        id_type = "pmid"
        record = _lookup_pubmed_pmid(pmid_m.group(1) if pmid_m else raw)
    elif arxiv_m or re.match(r"^\d{4}\.\d{4,5}(?:v\d+)?$", raw):
        id_type = "arxiv"
        record = _lookup_arxiv_id(arxiv_m.group(1) if arxiv_m else raw)
    else:
        # Free-text title/citation lookup via Crossref
        q = urllib.parse.quote(raw)
        data = _http_get_json(f"https://api.crossref.org/works?query.bibliographic={q}&rows=1")
        items = (data or {}).get("message", {}).get("items", [])
        if items and items[0].get("DOI"):
            candidate = _lookup_crossref_doi(items[0]["DOI"])
            if candidate and _title_similarity(claimed_title or raw, candidate.get("title", "")) >= 0.55:
                record = candidate

    if not record:
        return {
            "verified": False,
            "verdict": "FABRICATED_OR_UNRESOLVED",
            "identifier_type": id_type,
            "query": raw,
            "issues": [f"Identifier or citation '{raw}' does not resolve in Crossref, DataCite, PubMed, or arXiv."],
            "recommendation": "Remove or replace this citation; it appears to be hallucinated or contains a broken identifier.",
        }

    issues: list[str] = []
    checks: dict[str, Any] = {}

    if claimed_title:
        sim = _title_similarity(claimed_title, record.get("title", ""))
        checks["title_similarity"] = sim
        if sim < 0.48:
            issues.append(
                f"CHIMERA TITLE MISMATCH: Claimed title '{claimed_title}' does not match registry title "
                f"'{record.get('title')}' (similarity={sim:.0%})."
            )

    if claimed_author:
        c_auth = _normalize_text(claimed_author)
        actual_authors_norm = " ".join(_normalize_text(a) for a in record.get("authors", []))
        author_match = any(tok in actual_authors_norm for tok in c_auth.split() if len(tok) > 2)
        checks["author_match"] = author_match
        if not author_match and record.get("authors"):
            issues.append(
                f"CHIMERA AUTHOR MISMATCH: Claimed author '{claimed_author}' not found among actual authors "
                f"({', '.join(record.get('authors', [])[:4])})."
            )

    if claimed_year is not None and str(claimed_year).strip().isdigit() and record.get("year"):
        c_yr = int(str(claimed_year).strip())
        a_yr = int(record["year"])
        checks["year_delta"] = abs(c_yr - a_yr)
        if abs(c_yr - a_yr) > 1:
            issues.append(f"YEAR MISMATCH: Claimed publication year {c_yr} differs from official registry year {a_yr}.")

    if record.get("is_retracted"):
        issues.append(f"RETRACTED PAPER ALERT: This work has been flagged as RETRACTED ({', '.join(record.get('retraction_notices', []))}).")

    if record.get("is_retracted"):
        verdict = "RETRACTED"
        verified = False
    elif issues:
        verdict = "CHIMERA_MISMATCH"
        verified = False
    else:
        verdict = "VERIFIED"
        verified = True

    return {
        "verified": verified,
        "verdict": verdict,
        "identifier_type": id_type,
        "registry": record.get("registry"),
        "record": record,
        "checks": checks,
        "issues": issues,
        "bibtex": _format_bibtex(record),
        "apa": _format_apa(record),
    }


def _extract_citations_from_text(text: str) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Extract BibTeX entries if present
    for m in BIBTEX_ENTRY_REGEX.finditer(text):
        key = m.group(2).strip()
        body = m.group(3)
        doi_m = re.search(r"doi\s*=\s*[\{\"]([^\"}]+)[\"\}]", body, re.IGNORECASE)
        title_m = re.search(r"title\s*=\s*[\{\"]([^\"}]+)[\"\}]", body, re.IGNORECASE)
        author_m = re.search(r"author\s*=\s*[\{\"]([^\"}]+)[\"\}]", body, re.IGNORECASE)
        year_m = re.search(r"year\s*=\s*[\{\"]?(\d{4})[\"\}]?", body, re.IGNORECASE)
        ident = _clean_doi(doi_m.group(1)) if doi_m else (title_m.group(1).strip() if title_m else key)
        dedup_k = ident.lower()
        if dedup_k not in seen:
            seen.add(dedup_k)
            extracted.append({
                "source_label": f"BibTeX @{key}",
                "identifier": ident,
                "claimed_title": title_m.group(1).strip("{}") if title_m else None,
                "claimed_author": author_m.group(1).split(" and ")[0].strip("{}") if author_m else None,
                "claimed_year": int(year_m.group(1)) if year_m else None,
            })

    # 2. Extract inline DOIs
    for m in DOI_REGEX.finditer(text):
        doi = _clean_doi(m.group(1))
        if doi.lower() not in seen:
            seen.add(doi.lower())
            extracted.append({
                "source_label": f"DOI {doi}",
                "identifier": doi,
                "claimed_title": None,
                "claimed_author": None,
                "claimed_year": None,
            })

    # 3. Extract inline PMIDs
    for m in PMID_REGEX.finditer(text):
        pmid = f"PMID:{m.group(1)}"
        if pmid.lower() not in seen:
            seen.add(pmid.lower())
            extracted.append({
                "source_label": pmid,
                "identifier": pmid,
                "claimed_title": None,
                "claimed_author": None,
                "claimed_year": None,
            })

    # 4. Extract inline arXiv IDs
    for m in ARXIV_REGEX.finditer(text):
        ax = f"arXiv:{m.group(1)}"
        if ax.lower() not in seen:
            seen.add(ax.lower())
            extracted.append({
                "source_label": ax,
                "identifier": ax,
                "claimed_title": None,
                "claimed_author": None,
                "claimed_year": None,
            })

    return extracted


def audit_text(text: str, max_workers: int = 6) -> dict[str, Any]:
    """
    Scan any Markdown, LaTeX, BibTeX, or LLM response text, extract all DOIs, PMIDs, arXiv IDs,
    and BibTeX entries, verify each concurrently, and return an overall Citation Integrity Report.
    """
    items = _extract_citations_from_text(text)
    if not items:
        return {
            "total_citations": 0,
            "verified_count": 0,
            "chimera_count": 0,
            "fabricated_count": 0,
            "retracted_count": 0,
            "integrity_score": 100.0,
            "results": [],
            "summary": "No DOIs, PMIDs, arXiv IDs, or BibTeX entries found in the provided text.",
        }

    def _check_one(item: dict[str, Any]) -> dict[str, Any]:
        res = verify_citation(
            item["identifier"],
            claimed_title=item.get("claimed_title"),
            claimed_author=item.get("claimed_author"),
            claimed_year=item.get("claimed_year"),
        )
        res["source_label"] = item["source_label"]
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_check_one, items))

    verified_count = sum(1 for r in results if r["verdict"] == "VERIFIED")
    chimera_count = sum(1 for r in results if r["verdict"] == "CHIMERA_MISMATCH")
    fabricated_count = sum(1 for r in results if r["verdict"] == "FABRICATED_OR_UNRESOLVED")
    retracted_count = sum(1 for r in results if r["verdict"] == "RETRACTED")
    total = len(results)
    score = round((verified_count / total) * 100.0, 1) if total else 100.0

    return {
        "total_citations": total,
        "verified_count": verified_count,
        "chimera_count": chimera_count,
        "fabricated_count": fabricated_count,
        "retracted_count": retracted_count,
        "integrity_score": score,
        "results": results,
        "summary": (
            f"Audited {total} citation(s): {verified_count} VERIFIED, "
            f"{chimera_count} CHIMERA_MISMATCH, {fabricated_count} FABRICATED/BROKEN, "
            f"{retracted_count} RETRACTED (Integrity Score: {score}%)."
        ),
    }


def search_verified_literature(query: str, limit: int = 5, source: str = "all") -> dict[str, Any]:
    """
    Search Crossref, OpenAlex, PubMed, and arXiv for real, registry-verified scientific papers
    with ready-to-cite DOIs and BibTeX.
    """
    limit = max(1, min(int(limit), 20))
    results: list[dict[str, Any]] = []
    seen_dois: set[str] = set()

    if source in ("all", "openalex", "crossref"):
        q = urllib.parse.quote(query)
        oa = _http_get_json(f"https://api.openalex.org/works?search={q}&per-page={limit}")
        for w in (oa or {}).get("results", [])[:limit]:
            raw_doi = w.get("doi") or ""
            doi = _clean_doi(raw_doi) if raw_doi else None
            if doi and doi.lower() in seen_dois:
                continue
            if doi:
                seen_dois.add(doi.lower())
            authors = [
                a.get("author", {}).get("display_name")
                for a in w.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            rec = {
                "registry": "OpenAlex",
                "title": w.get("title") or "Untitled",
                "authors": authors[:8],
                "year": w.get("publication_year"),
                "journal": src.get("display_name") or "OpenAlex",
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else w.get("id"),
                "open_access_url": (w.get("open_access") or {}).get("oa_url"),
                "citation_count": w.get("cited_by_count", 0),
                "is_retracted": bool(w.get("is_retracted")),
            }
            rec["bibtex"] = _format_bibtex(rec)
            rec["apa"] = _format_apa(rec)
            results.append(rec)

    if source in ("all", "pubmed") and len(results) < limit:
        q = urllib.parse.quote(query)
        es = _http_get_json(
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}&retmax={limit}&retmode=json"
        )
        id_list = (es or {}).get("esearchresult", {}).get("idlist", [])
        for pmid in id_list:
            if len(results) >= limit:
                break
            rec = _lookup_pubmed_pmid(pmid)
            if rec:
                doi = rec.get("doi")
                if doi and doi.lower() in seen_dois:
                    continue
                if doi:
                    seen_dois.add(doi.lower())
                rec["bibtex"] = _format_bibtex(rec)
                rec["apa"] = _format_apa(rec)
                results.append(rec)

    if source in (" arxiv", "arxiv") or (source == "all" and len(results) < limit):
        q = urllib.parse.quote(query)
        xml_txt = _http_get_text(f"https://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results={limit}")
        if xml_txt:
            try:
                root = ET.fromstring(xml_txt)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall("atom:entry", ns):
                    if len(results) >= limit:
                        break
                    id_el = entry.find("atom:id", ns)
                    if id_el is not None and id_el.text:
                        ax_id = id_el.text.rstrip("/").split("/abs/")[-1]
                        rec = _lookup_arxiv_id(ax_id)
                        if rec:
                            rec["bibtex"] = _format_bibtex(rec)
                            rec["apa"] = _format_apa(rec)
                            results.append(rec)
            except Exception:
                pass

    return {
        "query": query,
        "count": len(results[:limit]),
        "results": results[:limit],
    }


def generate_bibtex(identifiers: list[str]) -> dict[str, Any]:
    """Resolve a list of DOIs, PMIDs, or arXiv IDs into verified BibTeX entries."""
    entries: list[str] = []
    failed: list[str] = []
    for ident in identifiers:
        res = verify_citation(ident)
        if res.get("bibtex"):
            entries.append(res["bibtex"])
        else:
            failed.append(ident)
    return {
        "resolved_count": len(entries),
        "failed": failed,
        "bibtex": "\n\n".join(entries),
    }
