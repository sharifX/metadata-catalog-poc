"""DigiLab catalogue API: search with policy evaluation, DCAT/CDIF representations, catalogue registration."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import duckdb
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import harvest as harvester
from .common import (DATA_DIR, PARTNER_PUBLIC_BASE, extract_datasets, fetch_graph, load_registered, load_sources, matches,
                     save_registered, source_id_for, to_internal, to_public, vocab)
from .policy import evaluate

app = FastAPI(
    title="DigiLab catalogue demo API",
    description="Cross-partner dataset search over harvested DCAT-AP catalogues, with ODRL offer evaluation "
                "and CDIF representations. All partner data is mock.",
)
# Partner pages (another origin) read /api/sources to show whether they are listed.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
STATIC = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
LD = "application/ld+json"


def _index_rows(q="", dataset_id="", source="", asset_type=""):
    if not os.path.exists(harvester.INDEX):
        return []
    sql, params, where = f"SELECT record FROM read_parquet('{harvester.INDEX}')", [], []
    for t in (q or "").lower().split():
        where.append("lower(title || ' ' || description || ' ' || array_to_string(keywords, ' ')) LIKE ?")
        params.append(f"%{t}%")
    if dataset_id:
        where.append("id = ?"); params.append(dataset_id)
    if source:
        where.append("source = ?"); params.append(source)
    if asset_type:
        where.append("asset_type = ?"); params.append(asset_type)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [json.loads(r[0]) for r in duckdb.connect().execute(sql + " ORDER BY source, title", params).fetchall()]


def _live_rows(q="", dataset_id="", source="", asset_type=""):
    """Fetch every partner catalogue at query time (no index). Failures show up as unavailable sources."""
    def one(src):
        try:
            return extract_datasets(fetch_graph(src["url"], retries=1), src), None
        except RuntimeError as e:
            return [], {"source": src["id"], "error": str(e)}
    srcs = [s for s in load_sources() if not source or s["id"] == source]
    rows, errors = [], []
    with ThreadPoolExecutor() as pool:
        for ds_rows, err in pool.map(one, srcs):
            rows += [r for r in ds_rows if matches(r, q) and (not dataset_id or r["id"] == dataset_id)
                     and (not asset_type or r["asset_type"] == asset_type)]
            if err:
                errors.append(err)
    return sorted(rows, key=lambda r: (r["source"], r["title"])), errors


def _one(dataset_id):
    rows = _index_rows(dataset_id=dataset_id)
    if not rows:
        raise HTTPException(404, f"dataset not in index: {dataset_id}")
    return rows[0]


@app.get("/api/search", tags=["search"])
def search(q: str = "", purpose: str = "", spatial: str = "", action: str = "use",
           mode: str = Query("index", pattern="^(index|live)$"), only_conformant: bool = False,
           dataset: str = Query("", description="exact asset IRI"), source: str = "",
           type: str = Query("", pattern="^(|dataset|software)$", description="asset type")):
    """Search across partner catalogues; every hit carries a policy verdict for the stated request."""
    t0 = time.perf_counter()
    rows, errors = (_index_rows(q, dataset, source, type), []) if mode == "index" else _live_rows(q, dataset, source, type)
    if only_conformant:
        rows = [r for r in rows if r["conforms"]]
    request = {"action": action, "purpose": purpose, "spatial": spatial}
    for r in rows:
        r["evaluation"] = evaluate(r["policy"], request)
        for k in ("dcat", "cdif", "codemeta"):
            r.pop(k, None)  # available via the representation endpoints
    return {"mode": mode, "request": request, "count": len(rows), "unavailable_sources": errors,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1), "results": rows}


@app.get("/api/dataset", tags=["dataset"])
def dataset(id: str):
    """The harvested record for one dataset (JSON)."""
    row = _one(id)
    for k in ("dcat", "cdif", "codemeta"):
        row.pop(k, None)
    return row


@app.get("/api/dataset/dcat", tags=["dataset"], response_class=JSONResponse)
def dataset_dcat(id: str):
    """The dataset as published by the partner: DCAT-AP + ODRL JSON-LD."""
    return JSONResponse(_one(id)["dcat"], media_type=LD)


@app.get("/api/dataset/cdif", tags=["dataset"], response_class=JSONResponse)
def dataset_cdif(id: str):
    """The same dataset crosswalked to a CDIF Data Description (schema.org JSON-LD)."""
    row = _one(id)
    if "cdif" not in row:
        raise HTTPException(404, "CDIF is generated for datasets; use /api/dataset/codemeta for software")
    return JSONResponse(row["cdif"], media_type=LD)


@app.get("/api/dataset/codemeta", tags=["dataset"], response_class=JSONResponse)
def dataset_codemeta(id: str):
    """A software asset crosswalked to CodeMeta (schema.org SoftwareSourceCode JSON-LD)."""
    row = _one(id)
    if "codemeta" not in row:
        raise HTTPException(404, "CodeMeta is generated for software; use /api/dataset/cdif for datasets")
    return JSONResponse(row["codemeta"], media_type=LD)


@app.get("/api/sources", tags=["catalogues"])
def sources():
    """Registered partner catalogues and the last harvest report."""
    path = os.path.join(DATA_DIR, "harvest-report.json")
    last = json.load(open(path)) if os.path.exists(path) else None
    return {"sources": load_sources(), "last_harvest": last, "partner_hosting": PARTNER_PUBLIC_BASE + "/"}


@app.post("/api/sources", tags=["catalogues"])
def register(url: str = Body(..., embed=True), name: str = Body("", embed=True)):
    """Register a new partner catalogue by URL: fetch, SHACL-check against the agreed minimum, then harvest."""
    internal = to_internal(url.strip())
    try:
        g = fetch_graph(internal, retries=1)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    sid = source_id_for(internal)
    if any(s["id"] == sid for s in load_sources()):
        raise HTTPException(409, f"catalogue '{sid}' is already registered")
    entry = {"id": sid, "name": name or sid.upper(), "url": internal}
    src = {**entry, "origin": "registered", "catalogue_url": to_public(internal),
           "page_url": to_public(internal).rsplit("/", 1)[0] + "/"}
    rows = extract_datasets(g, src)  # validation preview before committing
    if not rows:
        raise HTTPException(400, "no dcat:Dataset found in that catalogue")
    save_registered(load_registered() + [entry])
    report = harvester.harvest(retries=1)
    return {"registered": next(r for r in report if r["source"] == sid), "harvest": report}


@app.delete("/api/sources/{source_id}", tags=["catalogues"])
def unregister(source_id: str):
    """Remove a catalogue that was registered through the API (configured ones stay)."""
    items = load_registered()
    if not any(s["id"] == source_id for s in items):
        raise HTTPException(404, "only catalogues registered through the API can be removed")
    save_registered([s for s in items if s["id"] != source_id])
    return {"harvest": harvester.harvest(retries=1)}


@app.post("/api/harvest", tags=["catalogues"])
def reharvest():
    """Re-harvest all registered catalogues."""
    return {"harvest": harvester.harvest(retries=1)}


@app.get("/api/vocab", tags=["vocabulary"])
def vocabulary():
    """Keyword/theme/purpose → concept mappings (stand-in for the DigiLab Vocabulary Hub)."""
    return vocab()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/standards", include_in_schema=False)
def standards():
    return FileResponse(os.path.join(STATIC, "standards.html"))


@app.get("/shape.ttl", include_in_schema=False)
def shape():
    from .common import SHAPES
    return FileResponse(SHAPES, media_type="text/turtle")
