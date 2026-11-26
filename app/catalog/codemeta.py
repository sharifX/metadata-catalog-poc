"""Crosswalk a harvested software record (dcat:Resource + schema:SoftwareSourceCode) to CodeMeta JSON-LD.

CodeMeta is the schema.org-based metadata standard for research software; it plays the role for software
that CDIF plays for data. Demo crosswalk, not validated.
"""

def to_codemeta(row):
    doc = {
        "@context": "https://w3id.org/codemeta/3.0",
        "@type": "SoftwareSourceCode",
        "@id": row["id"],
        "identifier": row["identifier"] or row["id"],
        "name": row["title"],
        "description": row["description"],
        "codeRepository": row["code_repository"],
        "programmingLanguage": row["programming_language"],
        "license": row["license"],
        "keywords": [k["term"] for k in row["keywords"]],
        "publisher": {"@type": "Organization", "@id": row["publisher_id"], "name": row["publisher"]},
    }
    dois = [r for r in row["related"] if r.startswith("https://doi.org/")]
    if dois:
        doc["referencePublication"] = dois
    others = [r for r in row["related"] if not r.startswith("https://doi.org/")]
    if others:
        doc["relatedLink"] = others
    if row["based_on"]:
        doc["isBasedOn"] = row["based_on"]
    if row["policy"]:
        doc["conditionsOfAccess"] = "See ODRL offer " + row["policy"]["uid"]
    return {k: v for k, v in doc.items() if v not in (None, "", [])}
