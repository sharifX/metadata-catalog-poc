"""Crosswalk a harvested DCAT dataset record to a CDIF Data Description (schema.org-based) JSON-LD document.

Structure follows the CDIF profile-datadescription v1.1.1 example
(https://github.com/Cross-Domain-Interoperability-Framework/profile-datadescription). It is a demo
crosswalk, not validated against the CDIF SHACL shapes. Partners publish DCAT once; the catalogue
serves CDIF on request.
"""

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "cdif": "https://w3id.org/cdif/",
    "odrl": "http://www.w3.org/ns/odrl/2/",
}
QUDT = "http://qudt.org/vocab/unit/"


def _term(name, iri, scheme=None):
    t = {"@type": ["schema:DefinedTerm"], "schema:name": name, "schema:identifier": iri}
    if scheme:
        t["schema:inDefinedTermSet"] = scheme
    return t


def _variable(ds_id, v):
    var = {
        "@id": f"{ds_id}/var/{v['name']}",
        "@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
        "schema:name": v["name"],
        "schema:description": v["description"],
        "cdif:name": [v["name"]],
        # Demo heuristic: variables with a unit are measures, the rest describe the observation.
        "cdif:role": "Measure" if v["unit"] else "Descriptor",
    }
    if v["property"]:
        var["schema:propertyID"] = [_term(v["description"], v["property"])]
    if v["unit"]:
        unit = _term(v["unit"].removeprefix(QUDT), v["unit"], QUDT)
        var["schema:unitCode"] = unit
        var["cdi:describedUnitOfMeasure"] = unit
    return var


def _conditions(policy):
    if not policy:
        return "No machine-readable policy"
    parts = []
    for kind, rules in (("Permitted", policy["permissions"]), ("Prohibited", policy["prohibitions"])):
        for r in rules:
            cond = "; ".join(f'{c["leftOperand"]} {c["operator"]} {", ".join(c["rightOperand"])}' for c in r["constraints"])
            duty = f' (duties: {", ".join(r["duties"])})' if r["duties"] else ""
            parts.append(f'{kind}: {r["action"]}{" where " + cond if cond else ""}{duty}')
    return ". ".join(parts)


def to_cdif(row):
    ds_id = row["id"]
    doc = {
        "@context": CDIF_CONTEXT,
        "@id": ds_id,
        "@type": ["schema:Dataset"],
        "schema:name": row["title"],
        "schema:identifier": row["identifier"] or ds_id,
        "schema:url": ds_id,
        "schema:dateModified": row["modified"],
        "schema:license": [row["license"]] if row["license"] else [],
        "schema:keywords": [_term(k["label"], k["iri"], k["scheme"]) if k["mapped"] and k.get("match") == "exact" else k["term"]
                            for k in row["keywords"]],
        "schema:publisher": {"@id": row["publisher_id"], "@type": ["schema:Organization"], "schema:name": row["publisher"]},
        "schema:conditionsOfAccess": _conditions(row["policy"]),
    }
    if row["description"]:
        doc["schema:description"] = row["description"]
    if row["temporal_start"]:
        doc["schema:temporalCoverage"] = f'{row["temporal_start"]}/{row["temporal_end"] or ".."}'
    if row["spatial_iri"]:
        doc["schema:spatialCoverage"] = {"@type": ["schema:Place"], "schema:identifier": row["spatial_iri"],
                                         "schema:name": row["spatial"]}
    if row["policy"]:
        doc["odrl:hasPolicy"] = {"@id": row["policy"]["uid"]}
    doc["schema:subjectOf"] = {
        "@id": f"{ds_id}/metadata",
        "@type": ["schema:Dataset"],
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "schema:about": {"@id": ds_id},
        "schema:isBasedOn": {"@id": row["catalogue_url"]},
        "schema:dateModified": row["harvested_at"],
        "dcterms:conformsTo": [{"@id": "https://w3id.org/cdif/data_description/1.1"}],
    }
    if row["variables"]:
        doc["schema:variableMeasured"] = [_variable(ds_id, v) for v in row["variables"]]
    dist = {"@type": ["schema:DataDownload"]}
    if row["download_url"]:
        dist["schema:contentUrl"] = row["download_url"]
    elif row["access_url"]:
        dist["schema:url"] = row["access_url"]
        dist["schema:description"] = "Access on request"
    if row["media_type"]:
        dist["schema:encodingFormat"] = [row["media_type"]]
    doc["schema:distribution"] = [dist]
    return doc
