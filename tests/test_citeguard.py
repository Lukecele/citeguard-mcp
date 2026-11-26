from __future__ import annotations

import json
from unittest.mock import patch

from citeguard_mcp.server import handle_mcp_request
from citeguard_mcp.verifier import (
    _clean_doi,
    _extract_citations_from_text,
    _title_similarity,
    audit_text,
    verify_citation,
)


MOCK_ALPHAFOLD_RECORD = {
    "registry": "Crossref",
    "doi": "10.1038/s41586-021-03819-2",
    "title": "Highly accurate protein structure prediction with AlphaFold",
    "authors": ["Jumper, John", "Evans, Richard", "Pritzel, Alexander", "Hassabis, Demis"],
    "year": 2021,
    "journal": "Nature",
    "url": "https://doi.org/10.1038/s41586-021-03819-2",
    "citation_count": 25000,
    "is_retracted": False,
    "retraction_notices": [],
}

MOCK_RETRACTED_RECORD = {
    "registry": "Crossref",
    "doi": "10.1016/S0140-6736(97)11096-0",
    "title": "RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children",
    "authors": ["Wakefield, A. J."],
    "year": 1998,
    "journal": "The Lancet",
    "url": "https://doi.org/10.1016/S0140-6736(97)11096-0",
    "citation_count": 1500,
    "is_retracted": True,
    "retraction_notices": ["Retraction"],
}


def test_clean_doi():
    assert _clean_doi("https://doi.org/10.1038/s41586-021-03819-2.") == "10.1038/s41586-021-03819-2"
    assert _clean_doi("DOI: 10.5281/zenodo.24393472)") == "10.5281/zenodo.24393472"


def test_title_similarity():
    assert _title_similarity(
        "Highly accurate protein structure prediction with AlphaFold",
        "Highly accurate protein structure prediction with AlphaFold",
    ) == 1.0
    assert _title_similarity(
        "Quantum teleportation in superconducting qubits",
        "Highly accurate protein structure prediction with AlphaFold",
    ) < 0.2


@patch("citeguard_mcp.verifier._http_get_json", return_value=None)
@patch("citeguard_mcp.verifier._lookup_crossref_doi", return_value=MOCK_ALPHAFOLD_RECORD)
def test_verify_citation_verified(mock_cr, mock_oa):
    res = verify_citation(
        "10.1038/s41586-021-03819-2",
        claimed_title="Highly accurate protein structure prediction with AlphaFold",
        claimed_author="Jumper",
        claimed_year=2021,
    )
    assert res["verified"] is True
    assert res["verdict"] == "VERIFIED"
    assert "jumper2021highly" in res["bibtex"]


@patch("citeguard_mcp.verifier._http_get_json", return_value=None)
@patch("citeguard_mcp.verifier._lookup_crossref_doi", return_value=MOCK_ALPHAFOLD_RECORD)
def test_verify_citation_chimera_detection(mock_cr, mock_oa):
    res = verify_citation(
        "10.1038/s41586-021-03819-2",
        claimed_title="Deep reinforcement learning for autonomous fusion reactors",
        claimed_author="Einstein",
        claimed_year=2024,
    )
    assert res["verified"] is False
    assert res["verdict"] == "CHIMERA_MISMATCH"
    assert len(res["issues"]) == 3


@patch("citeguard_mcp.verifier._lookup_openalex_doi", return_value=None)
@patch("citeguard_mcp.verifier._lookup_datacite_doi", return_value=None)
@patch("citeguard_mcp.verifier._lookup_crossref_doi", return_value=None)
def test_verify_citation_fabricated_doi(mock_cr, mock_dc, mock_oa):
    res = verify_citation("10.9999/hallucinated.fake.doi.2026")
    assert res["verified"] is False
    assert res["verdict"] == "FABRICATED_OR_UNRESOLVED"


@patch("citeguard_mcp.verifier._lookup_openalex_doi", return_value={**MOCK_ALPHAFOLD_RECORD, "registry": "OpenAlex"})
@patch("citeguard_mcp.verifier._lookup_datacite_doi", return_value=None)
@patch("citeguard_mcp.verifier._lookup_crossref_doi", return_value=None)
def test_verify_citation_openalex_fallback_when_crossref_down(mock_cr, mock_dc, mock_oa):
    res = verify_citation("10.1038/s41586-021-03819-2")
    assert res["verified"] is True
    assert res["verdict"] == "VERIFIED"
    assert res["registry"] == "OpenAlex"


def test_verify_citation_registry_unavailable_on_network_failure():
    import urllib.error

    def _raise_503(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.crossref.org", 503, "Service Unavailable", {}, None)

    with patch("urllib.request.urlopen", side_effect=_raise_503):
        res = verify_citation("10.1038/s41586-021-03819-2")
        assert res["verified"] is False
        assert res["verdict"] == "REGISTRY_UNAVAILABLE"
        assert res.get("network_error") is True

        report = audit_text("See DOI: 10.1038/s41586-021-03819-2")
        assert report["unavailable_count"] == 1
        assert report["fabricated_count"] == 0


@patch("citeguard_mcp.verifier._lookup_crossref_doi", return_value=MOCK_RETRACTED_RECORD)
def test_verify_citation_retracted(mock_cr):
    res = verify_citation("10.1016/S0140-6736(97)11096-0")
    assert res["verified"] is False
    assert res["verdict"] == "RETRACTED"


def test_extract_citations_from_text():
    sample = """
    As shown in AlphaFold (DOI: 10.1038/s41586-021-03819-2) and Transformer (arXiv:1706.03762),
    clinical trials (PMID: 37257442) confirm the result.
    """
    items = _extract_citations_from_text(sample)
    assert len(items) == 3
    ids = [i["identifier"] for i in items]
    assert "10.1038/s41586-021-03819-2" in ids
    assert "PMID:37257442" in ids
    assert "arXiv:1706.03762" in ids


def test_mcp_jsonrpc_lifecycle():
    init_resp = handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert init_resp["result"]["serverInfo"]["name"] == "citeguard-mcp"

    tools_resp = handle_mcp_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
    assert {
        "verify_citation",
        "audit_document_citations",
        "search_verified_literature",
        "generate_bibtex",
        "check_retraction",
    } <= tool_names
