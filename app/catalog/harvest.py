"""Harvest every registered partner catalogue into a Parquet index (queried with DuckDB)."""
import json
import os
import sys
import time

import duckdb

from .common import DATA_DIR, extract_datasets, fetch_graph, load_sources

INDEX = os.path.join(DATA_DIR, "index.parquet")


def write_index(rows, path=INDEX):
    """A few searchable columns plus the full record as JSON."""
    con = duckdb.connect()
    con.execute("""CREATE TABLE datasets (id VARCHAR, asset_type VARCHAR, source VARCHAR, publisher VARCHAR, title VARCHAR,
                   description VARCHAR, keywords VARCHAR[], conforms BOOLEAN, modified VARCHAR,
                   harvested_at VARCHAR, record VARCHAR)""")
    con.executemany("INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        [r["id"], r["asset_type"], r["source"], r["publisher"], r["title"], r["description"],
         [k["term"] for k in r["keywords"]], r["conforms"], r["modified"], r["harvested_at"], json.dumps(r)]
        for r in rows])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    con.execute(f"COPY datasets TO '{tmp}' (FORMAT parquet)")
    os.replace(tmp, path)  # atomic swap so the API never reads a half-written file


def harvest_source(src, retries=10):
    g = fetch_graph(src["url"], retries=retries)
    rows = extract_datasets(g, src)
    bad = [r for r in rows if not r["conforms"]]
    return rows, {"source": src["id"], "name": src["name"], "ok": True, "origin": src["origin"],
                  "catalogue_url": src["catalogue_url"], "page_url": src["page_url"],
                  "datasets": len(rows), "nonconformant": len(bad),
                  "issues": {r["title"]: r["conformance_issues"] for r in bad}}


def harvest(retries=10):
    rows, report = [], []
    for src in load_sources():
        try:
            src_rows, rep = harvest_source(src, retries)
        except RuntimeError as e:
            print(f"  ! {src['id']}: {e}", file=sys.stderr)
            report.append({"source": src["id"], "name": src["name"], "ok": False, "origin": src["origin"],
                           "catalogue_url": src["catalogue_url"], "page_url": src["page_url"], "error": str(e)})
            continue
        print(f"  {src['id']:<10} {rep['datasets']} assets, {rep['nonconformant']} below agreed minimum")
        for title, issues in rep["issues"].items():
            print(f"     - {title}: {'; '.join(issues)}")
        rows += src_rows
        report.append(rep)
    write_index(rows)
    with open(os.path.join(DATA_DIR, "harvest-report.json"), "w") as f:
        json.dump({"harvested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": report}, f, indent=2)
    print(f"Indexed {len(rows)} assets from {sum(r['ok'] for r in report)} catalogues -> {INDEX}")
    return report


if __name__ == "__main__":
    harvest()
