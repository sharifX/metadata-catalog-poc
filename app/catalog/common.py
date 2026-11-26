"""Fetch partner DCAT+ODRL catalogues and flatten them into dataset records.

Shared by the harvester (index mode), the API (live mode) and catalogue registration.
"""
import json
import os
import re
import time

import requests
from pyshacl import validate
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCAT, DCTERMS, FOAF, RDF

from .cdif import to_cdif
from .codemeta import to_codemeta

ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
SDO = Namespace("http://schema.org/")
SH = Namespace("http://www.w3.org/ns/shacl#")

HERE = os.path.dirname(__file__)
PARTNER_BASE = os.environ.get("PARTNER_BASE", "http://localhost:8080")            # used to fetch
PARTNER_PUBLIC_BASE = os.environ.get("PARTNER_PUBLIC_BASE", "http://localhost:8080")  # shown in links
SOURCES = os.environ.get("SOURCES", os.path.join(HERE, "../../config/sources.json"))
SHAPES = os.environ.get("SHAPES", os.path.join(HERE, "../../config/shapes/dcat-odrl-min.ttl"))
VOCAB = os.environ.get("VOCAB", os.path.join(HERE, "../../config/vocab.json"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "../../data"))
REGISTERED = os.path.join(DATA_DIR, "registered-sources.json")

# Context used when serving a single dataset back as DCAT JSON-LD.
DCAT_CONTEXT = {
    "dcat": str(DCAT), "dct": str(DCTERMS), "odrl": str(ODRL), "foaf": str(FOAF),
    "schema": str(SDO), "xsd": "http://www.w3.org/2001/XMLSchema#",
}


# ---------- sources ----------

def to_public(url):
    return url.replace(PARTNER_BASE, PARTNER_PUBLIC_BASE, 1) if PARTNER_BASE != PARTNER_PUBLIC_BASE else url


def to_internal(url):
    return url.replace(PARTNER_PUBLIC_BASE, PARTNER_BASE, 1) if PARTNER_BASE != PARTNER_PUBLIC_BASE else url


def _expand(src, origin):
    src = dict(src, origin=origin)
    src["url"] = src["url"].replace("{PARTNER_BASE}", PARTNER_BASE)
    src["catalogue_url"] = to_public(src["url"])
    src["page_url"] = src["catalogue_url"].rsplit("/", 1)[0] + "/"
    return src


def load_registered():
    if not os.path.exists(REGISTERED):
        return []
    with open(REGISTERED) as f:
        return json.load(f)


def save_registered(items):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REGISTERED, "w") as f:
        json.dump(items, f, indent=2)


def load_sources():
    with open(SOURCES) as f:
        configured = [_expand(s, "config") for s in json.load(f)]
    known = {s["id"] for s in configured}
    registered = [_expand(s, "registered") for s in load_registered() if s["id"] not in known]
    return configured + registered


def source_id_for(url):
    parts = [p for p in re.split(r"[/:.]+", url) if p and p not in ("http", "https", "catalog", "jsonld", "json")]
    return re.sub(r"[^a-z0-9-]", "", (parts[-1] if parts else "source").lower()) or "source"


_vocab = None


def vocab():
    global _vocab
    if _vocab is None:
        with open(VOCAB) as f:
            _vocab = json.load(f)
    return _vocab


def concept(kind, term):
    """Look a term up in the vocabulary map (stand-in for the Vocabulary Hub)."""
    hit = vocab().get(kind, {}).get(term)
    if hit:
        return dict(hit, term=term, mapped=True)
    search = vocab()["unmapped_search"]
    return {"term": term, "mapped": False, "scheme": search["scheme"],
            "iri": search["url"].replace("{term}", requests.utils.quote(term))}


# ---------- fetch + validate ----------

def fetch_graph(url, retries=10, wait=1.5):
    """GET a JSON-LD catalogue and parse it. Retries so compose start-up order doesn't matter."""
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            g = Graph()
            g.parse(data=r.text, format="json-ld", base=url)
            g.raw_json = json.loads(r.text)  # keep the partner's own (nested) JSON-LD for display
            return g
        except Exception as e:  # noqa: BLE001 - demo: report and retry
            last = e
            if retries > 1:
                time.sleep(wait)
    raise RuntimeError(f"could not fetch {to_public(url)}: {last}")


_shapes = None


def check_conformance(g):
    """SHACL-validate a catalogue. Returns {dataset_iri: [messages]} for non-conforming datasets."""
    global _shapes
    if _shapes is None:
        _shapes = Graph().parse(SHAPES, format="turtle")
    conforms, report, _ = validate(g, shacl_graph=_shapes)
    problems = {}
    if not conforms:
        for res in report.subjects(RDF.type, SH.ValidationResult):
            focus = str(report.value(res, SH.focusNode))
            problems.setdefault(focus, []).append(str(report.value(res, SH.resultMessage)))
    return problems


# ---------- flatten ----------

def _short(term):
    if term is None:
        return None
    s = str(term)
    for ns in (str(ODRL), "http://publications.europa.eu/resource/authority/data-theme/",
               "http://publications.europa.eu/resource/authority/country/",
               "https://www.iana.org/assignments/media-types/"):
        if s.startswith(ns):
            return s[len(ns):]
    return s


def _rule(g, node):
    constraints = []
    for c in g.objects(node, ODRL.constraint):
        constraints.append({
            "leftOperand": _short(g.value(c, ODRL.leftOperand)),
            "operator": _short(g.value(c, ODRL.operator)),
            "rightOperand": sorted(str(o) for o in g.objects(c, ODRL.rightOperand)),
        })
    return {
        "action": _short(g.value(node, ODRL.action)),
        "constraints": constraints,
        "duties": sorted(_short(g.value(d, ODRL.action)) for d in g.objects(node, ODRL.duty)),
    }


def extract_policy(g, policy):
    if policy is None:
        return None
    return {
        "uid": str(policy),
        "type": _short(g.value(policy, RDF.type)),
        "assigner": str(g.value(policy, ODRL.assigner) or ""),
        "permissions": [_rule(g, p) for p in g.objects(policy, ODRL.permission)],
        "prohibitions": [_rule(g, p) for p in g.objects(policy, ODRL.prohibition)],
    }


def _variables(g, ds):
    out = []
    for v in g.objects(ds, SDO.variableMeasured):
        out.append({
            "name": str(g.value(v, SDO.name) or ""),
            "description": str(g.value(v, SDO.description) or ""),
            "unit": str(g.value(v, SDO.unitCode) or ""),
            "property": str(g.value(v, SDO.propertyID) or ""),
        })
    return sorted(out, key=lambda x: x["name"])


def _raw_node(g, ds):
    raw = getattr(g, "raw_json", None)
    if not isinstance(raw, dict):
        return None
    for node in (raw.get("dcat:dataset", []) or []) + (raw.get("dcat:resource", []) or []):
        if isinstance(node, dict) and node.get("@id") == str(ds):
            out = {"@context": raw.get("@context")}
            out.update(node)
            out["dct:publisher"] = {k: v for k, v in raw.get("dct:publisher", {}).items()} or node.get("dct:publisher")
            out["dcat:catalog"] = {"@id": raw.get("@id")}
            return out
    return None


def dataset_dcat(g, ds):
    """The dataset as the partner published it (nested JSON-LD); falls back to a graph serialisation."""
    raw = _raw_node(g, ds)
    if raw:
        return raw
    sub = Graph()
    for node in (ds, g.value(ds, ODRL.hasPolicy), g.value(ds, DCTERMS.publisher)):
        if node is not None:
            sub += g.cbd(node)
    return json.loads(sub.serialize(format="json-ld", context=DCAT_CONTEXT, auto_compact=True))


def _assets(g):
    """Datasets, plus software published as DCAT 3 catalogue resources."""
    for ds in g.subjects(RDF.type, DCAT.Dataset):
        yield ds, "dataset"
    for sw in g.subjects(RDF.type, SDO.SoftwareSourceCode):
        if (sw, RDF.type, DCAT.Dataset) not in g:
            yield sw, "software"


def extract_datasets(g, source):
    """Flatten every asset (dataset or software) in a catalogue into an index record."""
    problems = check_conformance(g)
    harvested_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = []
    for ds, asset_type in _assets(g):
        pub = g.value(ds, DCTERMS.publisher)
        temporal = g.value(ds, DCTERMS.temporal)
        dist = next(iter(g.objects(ds, DCAT.distribution)), None)
        row = {
            "id": str(ds),
            "asset_type": asset_type,
            "identifier": str(g.value(ds, DCTERMS.identifier) or ""),
            "source": source["id"],
            "catalogue_url": source["catalogue_url"],
            "page_url": source["page_url"],
            "publisher": str(g.value(pub, FOAF.name) or pub or ""),
            "publisher_id": str(pub or ""),
            "title": str(g.value(ds, DCTERMS.title) or ""),
            "description": str(g.value(ds, DCTERMS.description) or ""),
            "keywords": [concept("keywords", k) for k in sorted(str(k) for k in g.objects(ds, DCAT.keyword))],
            "themes": [concept("themes", _short(t)) for t in sorted(g.objects(ds, DCAT.theme))],
            "spatial": _short(g.value(ds, DCTERMS.spatial)),
            "spatial_iri": str(g.value(ds, DCTERMS.spatial) or ""),
            "temporal_start": str(g.value(temporal, DCAT.startDate) or "") if temporal else "",
            "temporal_end": str(g.value(temporal, DCAT.endDate) or "") if temporal else "",
            "modified": str(g.value(ds, DCTERMS.modified) or ""),
            "license": str(g.value(ds, DCTERMS.license) or ""),
            "media_type": _short(g.value(dist, DCAT.mediaType)) if dist else None,
            "download_url": str(g.value(dist, DCAT.downloadURL) or "") if dist else "",
            "access_url": str(g.value(dist, DCAT.accessURL) or "") if dist else "",
            "variables": _variables(g, ds),
            "landing_page": str(g.value(ds, DCAT.landingPage) or ""),
            "code_repository": str(g.value(ds, SDO.codeRepository) or ""),
            "programming_language": str(g.value(ds, SDO.programmingLanguage) or ""),
            "related": sorted(str(r) for r in g.objects(ds, DCTERMS.relation)),
            "based_on": sorted(str(r) for r in g.objects(ds, SDO.isBasedOn)),
            "policy": extract_policy(g, g.value(ds, ODRL.hasPolicy)),
            "conforms": str(ds) not in problems,
            "conformance_issues": problems.get(str(ds), []),
            "harvested_at": harvested_at,
        }
        row["dcat"] = dataset_dcat(g, ds)
        row["policy_jsonld"] = row["dcat"].get("odrl:hasPolicy") if isinstance(row["dcat"], dict) else None
        if asset_type == "software":
            row["codemeta"] = to_codemeta(row)
        else:
            row["cdif"] = to_cdif(row)
        rows.append(row)
    return sorted(rows, key=lambda r: r["id"])


def matches(row, q):
    if not q:
        return True
    hay = " ".join([row["title"], row["description"], " ".join(k["term"] for k in row["keywords"])]).lower()
    return all(term in hay for term in q.lower().split())
