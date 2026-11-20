"""CIViC data plane: validate arguments, run one fixed GraphQL document, shape honest payloads.

Returns plain dicts and raises typed :mod:`civic_link.exceptions` errors; the MCP envelope
owns ``success``/``_meta``. CIViC answers an unknown ID with ``null`` and an unknown name
with ``totalCount: 0``. Both become ``not_found`` naming the offending argument, never a
silent empty list. A genuinely empty evidence answer is a success that says
"no CIViC evidence found", never "not actionable".
"""

from __future__ import annotations

import time
from typing import Any

from civic_link import queries as Q
from civic_link.api.client import CivicClient
from civic_link.exceptions import AmbiguousQueryError, InvalidInputError, NotFoundError
from civic_link.mcp.next_commands import cmd
from civic_link.shaping import (
    CAID,
    CLINVAR,
    COMPLEX_NOTE,
    COUNTS_NOTE,
    DOID_RE,
    FOREIGN_GENE,
    FOREIGN_GENE_HINT,
    HGVS,
    MP_MISS_HINT,
    NCBI_GENE,
    NCIT_RE,
    NO_EVIDENCE,
    NOT_A_REPORT,
    P_DOT,
    ROUTER_ONLY,
    SITE,
    SYMBOL,
    WS,
    VariantIndex,
    assertion_evidence,
    assertion_row,
    cursor,
    evidence_row,
    fence,
    gene_detail,
    gene_variant,
    hgvs_key,
    kind_totals,
    level_counts,
    match_notes,
    mp_detail,
    mp_row,
    now_iso,
    page_block,
    profile_note,
    variant_detail,
    variant_index,
)

#: CIViC silently truncates a page (100 nodes on most connections); no limit may exceed it.
UPSTREAM_PAGE_CAP = 100
DEFAULT_LIMIT = 10
MAX_LIMIT = 50  # fenced prose per row (standard/full) stays under the 128-fence ceiling
MP_DEFAULT_LIMIT = 25
GENE_DEFAULT_LIMIT = 50
VARIANT_INDEX_PATH = "/downloads/nightly/nightly-VariantSummaries.tsv"
VARIANT_INDEX_TTL_S = 86_400.0


def _page_args(limit: int, offset: int, maximum: int) -> None:
    if not 1 <= limit <= min(maximum, UPSTREAM_PAGE_CAP):
        raise InvalidInputError(f"`limit` must be 1-{maximum}.", field="limit")
    if offset < 0:
        raise InvalidInputError("`offset` must be >= 0.", field="offset")


_PAGING_FIELDS = {"first": "limit", "after": "offset"}
#: An unknown ID's own browse tool (no arguments needed); profiles/variants need a query.
_BROWSE = {"evidence_id": ("search_evidence_items",), "assertion_id": ("search_assertions",)}


def _named(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


class CivicService:
    """All CIViC queries; one instance per process over a shared client."""

    def __init__(self, client: CivicClient) -> None:
        """Bind the service to a rate-limited, cached upstream client."""
        self.client = client
        self._variant_index: tuple[float, VariantIndex] | None = None

    async def release(self) -> str | None:
        """Name of the latest monthly CIViC data release (cached), e.g. ``01-Nov-2026``."""
        data = await self.client.graphql(Q.RELEASES, {})
        names = [r.get("name") for r in data.get("dataReleases") or [] if isinstance(r, dict)]
        return next((n for n in names if n and n != "nightly"), None)

    async def _stamp(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        payload["data_version"] = f"CIViC {await self.release()}; live:{now}"
        payload["retrieved_at"] = now
        payload["disclaimer"] = NOT_A_REPORT
        return payload

    # -- lookups -------------------------------------------------------------------

    async def _variants(self, kind: str, value: str) -> list[dict[str, Any]]:
        """CIViC variants carrying a ClinVar ID or HGVS (nightly variant summary)."""
        if self._variant_index is None or self._variant_index[0] < time.monotonic():
            index = variant_index(await self.client.get_text(VARIANT_INDEX_PATH))
            self._variant_index = (time.monotonic() + VARIANT_INDEX_TTL_S, index)
        key = hgvs_key(value) if kind == "hgvs" else value
        hits = {h["variant_id"]: h for h in self._variant_index[1][kind].get(key, [])}
        return [hits[k] for k in sorted(hits)]

    async def _disease(self, disease: str) -> dict[str, Any]:
        """Filter variables for ``disease`` (DOID -> exact id; name -> CIViC name match)."""
        match = DOID_RE.fullmatch(disease.strip())
        variables = {"doid": match.group(1)} if match else {"disease": disease.strip()}
        data = await self.client.graphql(Q.DISEASE_LOOKUP, variables, fields={"doid": "disease"})
        found = data.get("diseases") or {}
        if not found.get("totalCount"):
            raise NotFoundError(
                "No CIViC disease matches `disease`.",
                field="disease",
                hint=(
                    "Give a DOID (DOID:1909) or a disease name as CIViC writes it (Melanoma). "
                    + ROUTER_ONLY.format(tool="mondo_resolve_disease")
                ),
                next_commands=[cmd("mondo_resolve_disease", query=disease.strip())],
            )
        if match:
            return {"disease_id": found["nodes"][0]["id"]}
        return {"disease_name": disease.strip()}

    async def _therapy(self, therapy: str) -> dict[str, Any]:
        """Filter variables for ``therapy`` (NCIt code -> exact id; name -> CIViC name match)."""
        match = NCIT_RE.fullmatch(therapy.strip())
        variables = {"ncit": match.group(1).upper()} if match else {"therapy": therapy.strip()}
        data = await self.client.graphql(Q.THERAPY_LOOKUP, variables, fields={"ncit": "therapy"})
        found = data.get("therapies") or {}
        if not found.get("totalCount"):
            raise NotFoundError(
                "No CIViC therapy matches `therapy`.",
                field="therapy",
                hint="Give an NCIt code (C64768) or a drug name as CIViC writes it (Vemurafenib).",
            )
        if match:
            return {"therapy_id": found["nodes"][0]["id"]}
        return {"therapy_name": therapy.strip()}

    async def _filters(self, disease: str | None, therapy: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if disease is not None:
            out.update(await self._disease(disease))
        if therapy is not None:
            out.update(await self._therapy(therapy))
        return out

    # -- molecular profiles -------------------------------------------------------

    async def search_molecular_profiles(
        self, query: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """Profile name / CAID / ClinVar ID / HGVS -> molecular profiles, simple and complex apart."""
        _page_args(limit, offset, UPSTREAM_PAGE_CAP)
        term = WS.sub(" ", query.strip())
        if not 1 <= len(term) <= 200:
            raise InvalidInputError("`query` must be 1-200 characters.", field="query")
        variables: dict[str, Any] = {"first": limit, "after": cursor(offset)}
        variant_id: int | None = None
        if CAID.fullmatch(term):
            kind, variables["caid"] = "caid", term.upper()
        elif (clinvar := CLINVAR.fullmatch(term)) or HGVS.fullmatch(term):
            kind = "clinvar" if clinvar else "hgvs"
            hits = await self._variants(kind, clinvar.group(1) if clinvar else term)
            if len(hits) > 1:  # e.g. ClinVar 13961 is on both BRAF V600E and BRAF V600
                raise AmbiguousQueryError(
                    f"This {kind} identifier is linked to {len(hits)} CIViC variants.",
                    field="query",
                    candidates=list[object](hits),
                    hint="Pick the variant you mean, or search by its CAID or name.",
                    next_commands=[
                        cmd("get_molecular_profile", molecular_profile_id=mp)
                        for h in hits[:3]
                        if (mp := h["single_variant_molecular_profile_id"])
                    ],
                )
            if hits:
                variant_id = variables["variant_id"] = hits[0]["variant_id"]
        else:
            kind, variables["name"] = "name", P_DOT.sub("", term)
        data: dict[str, Any] = {}
        if kind == "name" or "caid" in variables or variant_id is not None:
            data = await self.client.graphql(Q.MP_SEARCH, variables, fields=_PAGING_FIELDS)
        found = data.get("molecularProfiles") or {}
        total = int(found.get("totalCount") or 0)
        if total == 0:
            raise self._mp_miss(term, kind)
        rows = [mp_row(n) for n in found.get("nodes") or []]
        # the list a row sits in says its kind; dropping it per row saves tokens
        split: dict[str, list[dict[str, Any]]] = {"simple": [], "complex": []}
        for r in rows:
            split[r.pop("kind")].append(r)
        name = variables.get("name", term)
        payload: dict[str, Any] = {
            "query": term,
            "query_type": kind,
            "exact_match": self._exact(name, kind, found.get("nodes") or [], variant_id),
            **split,
            **page_block(total=total, returned=len(rows), limit=limit, offset=offset),
            **kind_totals(data, total),
        }
        if name != term:
            payload["query_normalized"] = name
        if variant_id is not None:
            payload["variant_id"] = variant_id
        if offset == 0:  # fixed notes once, on the first page
            payload["counts_note"] = COUNTS_NOTE
            if payload["complex"] or total > len(rows):  # complex rows here or on later pages
                payload["complex_note"] = COMPLEX_NOTE
        return await self._stamp(payload)

    @staticmethod
    def _exact(
        term: str, kind: str, nodes: list[dict[str, Any]], variant_id: int | None
    ) -> dict[str, Any] | None:
        """The single simple profile this query names (by name/alias), or the variant's own."""
        q = term.casefold()
        for node in nodes:
            if node.get("isComplex"):
                continue
            names = [str(node.get("name", "")), *(node.get("molecularProfileAliases") or [])]
            if kind != "name" or any(n.casefold() == q for n in names):
                return {"id": node.get("id"), "name": node.get("name")}
        return None

    @staticmethod
    def _mp_miss(term: str, kind: str) -> NotFoundError:
        gene = term.split(" ")[0]
        steps = [cmd("get_gene", gene=gene)] if kind == "name" and SYMBOL.fullmatch(gene) else []
        return NotFoundError(
            "No CIViC molecular profile matches this query.",
            field="query",
            hint=MP_MISS_HINT,
            candidates=[],
            next_commands=steps or [cmd("get_server_capabilities")],
        )

    async def get_molecular_profile(self, molecular_profile_id: int) -> dict[str, Any]:
        """One profile: component variants, evidence counts and its assertions."""
        data = await self.client.graphql(Q.MP_GET, {"molecular_profile_id": molecular_profile_id})
        raw = data.get("molecularProfile")
        if not raw:
            raise self._missing("molecular_profile_id", "molecular profile")
        detail = mp_detail(raw, data)
        conn = raw.get("assertions") or {}
        rejected = data.get("rejected_assertions") or {}  # absent from conn upstream
        rows = [assertion_row(a, "compact") for c in (conn, rejected) for a in c.get("nodes") or []]
        total = (conn.get("totalCount") or 0) + (rejected.get("totalCount") or 0)
        # ACCEPTED in full (as search_assertions defaults); unreviewed/rejected as stubs only
        accepted_assertions = [a for a in rows if a["status"] == "ACCEPTED"]
        stub = ("id", "name", "status", "assertion_type")
        others = [{k: a[k] for k in stub} for a in rows if a["status"] != "ACCEPTED"]
        payload: dict[str, Any] = {
            "molecular_profile": detail,
            "assertions": accepted_assertions,
            "other_assertions": others,
            "assertions_total": total,
            "assertions_truncated": total > len(rows),
        }
        if raw.get("isComplex"):
            payload["complex_note"] = COMPLEX_NOTE
        if not accepted_assertions:
            payload["evidence_note"] = profile_note(detail["evidence_counts_by_status"])
        return await self._stamp(payload)

    @staticmethod
    def _missing(field: str, what: str) -> NotFoundError:
        return NotFoundError(
            f"No CIViC {what} has this `{field}`.",
            field=field,
            hint="Find IDs with search_molecular_profiles(query) or get_gene(gene).",
            next_commands=[cmd(t) for t in _BROWSE.get(field, ())],
        )

    async def get_variant(self, variant_id: int) -> dict[str, Any]:
        """One variant: assembly-labelled coordinates and HGVS, CAID, ClinVar IDs, profiles."""
        raw = (await self.client.graphql(Q.VARIANT_GET, {"variant_id": variant_id})).get("variant")
        if not raw:
            raise self._missing("variant_id", "variant")
        return await self._stamp({"variant": variant_detail(raw)})

    # -- evidence & assertions ----------------------------------------------------

    async def _search(
        self,
        document: str,
        root: str,
        key: str,
        shape: Any,
        args: dict[str, Any],
        filters: dict[str, Any],
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        _page_args(limit, offset, MAX_LIMIT)
        variables = {
            **_named(**args),
            **filters,
            "first": limit,
            "after": cursor(offset),
        }
        fields = _PAGING_FIELDS | {
            f"{k}_{s}": k for k in ("disease", "therapy") for s in ("name", "id")
        }
        data = await self.client.graphql(document, variables, fields=fields)
        conn = data.get(root) or {}
        total = int(conn.get("totalCount") or 0)
        mp_id = args.get("molecular_profile_id")
        if total == 0 and mp_id is not None:  # an unknown profile is not_found, not "none"
            found = await self.client.graphql(Q.MP_GET, {"molecular_profile_id": mp_id})
            if not found.get("molecularProfile"):
                raise self._missing("molecular_profile_id", "molecular profile")
        rows = [shape(n) for n in conn.get("nodes") or []]
        payload: dict[str, Any] = {
            "filters": _named(**args),
            key: rows,
            **page_block(total=total, returned=len(rows), limit=limit, offset=offset),
        }
        if notes := match_notes(filters):
            payload["match_notes"] = notes
        if levels := level_counts(data):
            payload["counts_by_level"] = levels
        if total == 0:
            payload["evidence_note"] = NO_EVIDENCE
        return await self._stamp(payload)

    async def search_evidence_items(
        self,
        *,
        molecular_profile_id: int | None = None,
        disease: str | None = None,
        therapy: str | None = None,
        evidence_type: str | None = None,
        evidence_level: str | None = None,
        significance: str | None = None,
        status: str = "ACCEPTED",
        response_mode: str = "compact",
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Evidence items matching every given filter (accepted only by default)."""
        args = {
            "molecular_profile_id": molecular_profile_id,
            "evidence_type": evidence_type,
            "evidence_level": evidence_level,
            "significance": significance,
            "status": status,
        }
        filters = await self._filters(disease, therapy)
        payload = await self._search(
            Q.EVIDENCE_SEARCH,
            "evidenceItems",
            "evidence_items",
            lambda n: evidence_row(n, response_mode),
            args,
            filters,
            limit,
            offset,
        )
        payload["filters"].update(_named(disease=disease, therapy=therapy))
        return payload

    async def get_evidence_item(self, evidence_id: int) -> dict[str, Any]:
        """One evidence item with its fenced statement, source and linked assertions."""
        raw = (await self.client.graphql(Q.EVIDENCE_GET, {"evidence_id": evidence_id})).get(
            "evidenceItem"
        )
        if not raw:
            raise self._missing("evidence_id", "evidence item")
        item = evidence_row(raw, "full")
        source = raw.get("source") or {}
        item["source"]["title"] = fence(source.get("title"), str(raw.get("name")))
        item["source"]["clinical_trials"] = [
            t.get("nctId") for t in source.get("clinicalTrials") or []
        ]
        item["phenotypes"] = [
            {"hpo": p.get("hpoId"), "name": p.get("name")} for p in raw.get("phenotypes") or []
        ]
        item["assertions"] = raw.get("assertions") or []
        item["url"] = SITE + str(raw.get("link") or "")
        return await self._stamp({"evidence_item": item})

    async def search_assertions(
        self,
        *,
        molecular_profile_id: int | None = None,
        disease: str | None = None,
        therapy: str | None = None,
        assertion_type: str | None = None,
        amp_level: str | None = None,
        status: str = "ACCEPTED",
        response_mode: str = "compact",
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Assertions matching every given filter (accepted only by default)."""
        args = {
            "molecular_profile_id": molecular_profile_id,
            "assertion_type": assertion_type,
            "amp_level": amp_level,
            "status": status,
        }
        filters = await self._filters(disease, therapy)
        payload = await self._search(
            Q.ASSERTION_SEARCH,
            "assertions",
            "assertions",
            lambda n: assertion_row(n, response_mode),
            args,
            filters,
            limit,
            offset,
        )
        payload["filters"].update(_named(disease=disease, therapy=therapy))
        return payload

    async def get_assertion(self, assertion_id: int) -> dict[str, Any]:
        """One assertion: classification axes, fenced summary/description, linked EIDs."""
        raw = (await self.client.graphql(Q.ASSERTION_GET, {"assertion_id": assertion_id})).get(
            "assertion"
        )
        if not raw:
            raise self._missing("assertion_id", "assertion")
        item = assertion_row(raw, "full")
        item["description"] = fence(raw.get("description"), str(raw.get("name")))
        item["phenotypes"] = [
            {"hpo": p.get("hpoId"), "name": p.get("name")} for p in raw.get("phenotypes") or []
        ]
        item["evidence_items"] = [assertion_evidence(e) for e in raw.get("evidenceItems") or []]
        item["evidence_items_count"] = raw.get("evidenceItemsCount")
        item["url"] = SITE + str(raw.get("link") or "")
        return await self._stamp({"assertion": item})

    # -- genes ----------------------------------------------------------------------

    async def get_gene(self, gene: str, limit: int, offset: int) -> dict[str, Any]:
        """A CIViC gene (by symbol or NCBI Gene ID) and the variants curated for it."""
        _page_args(limit, offset, UPSTREAM_PAGE_CAP)
        value = gene.strip()
        if FOREIGN_GENE.fullmatch(value):
            raise InvalidInputError(
                "`gene` takes a symbol or NCBI Gene ID; CIViC has no Ensembl or HGNC ID lookup.",
                field="gene",
                allowed_values=["HGNC symbol (BRAF)", "NCBI Gene ID (NCBIGene:673 or 673)"],
                hint=FOREIGN_GENE_HINT,
                next_commands=[cmd("hgnc_resolve_symbol", query=value)],
            )
        entrez = NCBI_GENE.fullmatch(value)
        if not entrez and not SYMBOL.fullmatch(value):
            raise InvalidInputError(
                "`gene` must be an HGNC symbol or an NCBI Gene ID.",
                field="gene",
                allowed_values=["HGNC symbol (BRAF)", "NCBI Gene ID (NCBIGene:673 or 673)"],
            )
        variables: dict[str, Any] = {"first": limit, "after": cursor(offset)}
        if entrez:
            variables["entrez_id"] = [int(entrez.group(1))]
        else:
            variables["symbol"] = [value.upper()]
        fields = {**_PAGING_FIELDS, "entrez_id": "gene", "symbol": "gene"}
        nodes = (
            (await self.client.graphql(Q.GENE_GET, variables, fields=fields)).get("genes") or {}
        ).get("nodes") or []
        if not nodes:
            raise NotFoundError(
                "CIViC curates no gene with this `gene`.",
                field="gene",
                hint="CIViC covers ~750 cancer genes; check the symbol. "
                + ROUTER_ONLY.format(tool="hgnc_resolve_symbol"),
                next_commands=[cmd("hgnc_resolve_symbol", query=value)],
            )
        raw = nodes[0]
        conn = raw.get("variants") or {}
        variants = [gene_variant(v) for v in conn.get("nodes") or []]
        return await self._stamp(
            {
                "gene": gene_detail(raw, first_page=offset == 0),
                "variants": variants,
                **page_block(
                    total=int(conn.get("totalCount") or 0),
                    returned=len(variants),
                    limit=limit,
                    offset=offset,
                ),
            }
        )
