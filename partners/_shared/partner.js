// Renders a partner's own landing page from its published catalog.jsonld (DCAT-AP + ODRL).
// Reads the compacted JSON-LD as published; no JSON-LD library needed for this demo.
(async function () {
  const CAT = window.DIGILAB_CATALOGUE;
  const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const arr = (x) => (x == null ? [] : Array.isArray(x) ? x : [x]);
  const id = (x) => (x && typeof x === "object" ? x["@id"] : x);
  const short = (iri) => String(iri || "").replace("http://www.w3.org/ns/odrl/2/", "").replace(/^odrl:/, "")
    .replace("http://publications.europa.eu/resource/authority/data-theme/", "")
    .replace("http://publications.europa.eu/resource/authority/country/", "");

  const raw = await (await fetch("catalog.jsonld")).json();
  const pub = raw["dct:publisher"] || {};
  const orgName = pub["foaf:name"] || id(pub);
  const sourceId = location.pathname.split("/").filter(Boolean).pop();
  document.title = `${orgName} — data catalogue (mock)`;

  function rule(r, kind) {
    const cons = arr(r["odrl:constraint"]).map((c) =>
      `<li>${esc(short(id(c["odrl:leftOperand"])))} <i>${esc(short(id(c["odrl:operator"])))}</i> ${arr(c["odrl:rightOperand"]).map(esc).join(", ")}</li>`).join("");
    const duties = arr(r["odrl:duty"]).map((d) => `<li>duty: ${esc(short(id(d["odrl:action"])))}</li>`).join("");
    return `<div class="rule ${kind === "permission" ? "perm" : "proh"}"><b>${kind}</b>: ${esc(short(id(r["odrl:action"])))}
      ${cons || duties ? `<ul>${cons}${duties}</ul>` : ""}</div>`;
  }
  function policyTree(p) {
    if (!p) return "<i>No policy published</i>";
    return `<div class="tree"><div>${esc(short(p["@type"]))} <code>${esc(p["@id"] || "")}</code></div>
      ${arr(p["odrl:permission"]).map((r) => rule(r, "permission")).join("")}
      ${arr(p["odrl:prohibition"]).map((r) => rule(r, "prohibition")).join("")}</div>`;
  }

  const header = el(`<div>
    <div class="mock">Mock partner website — the only thing a partner has to publish is <code>catalog.jsonld</code></div>
    <header>
      <div class="kicker">Data catalogue · DCAT-AP + ODRL</div>
      <h1>${esc(orgName)}</h1>
      <div class="row">
        <span>Catalogue IRI <code>${esc(raw["@id"])}</code></span>
        <a href="catalog.jsonld">catalog.jsonld ↗</a>
        <button class="link" id="showcat">view DCAT source</button>
        <span id="status" class="badge">checking DigiLab listing…</span>
        <a href="../">all partner sites</a>
      </div>
      <pre id="catsrc" hidden></pre>
    </header></div>`);
  document.body.append(...header.childNodes);
  document.getElementById("showcat").onclick = () => {
    const p = document.getElementById("catsrc");
    p.textContent = JSON.stringify(raw, null, 2); p.hidden = !p.hidden;
  };

  const main = document.createElement("main");
  document.body.append(main);
  const assets = [...arr(raw["dcat:dataset"]).map((d) => [d, false]), ...arr(raw["dcat:resource"]).map((d) => [d, true])];
  let shownSoftwareHeading = false;
  for (const [d, sw] of assets) {
    if (sw && !shownSoftwareHeading) { main.append(el(`<h2 class="section">Software</h2>`)); shownSoftwareHeading = true; }
    const t = d["dct:temporal"] || {};
    const dist = arr(d["dcat:distribution"])[0] || {};
    const repo = id(d["schema:codeRepository"]);
    const link = sw ? repo : (id(dist["dcat:downloadURL"]) || id(dist["dcat:accessURL"]));
    const linkText = sw ? "Code repository" : dist["dcat:downloadURL"] ? "Download" : "Request access";
    const meta = sw
      ? `Software · ${esc(d["schema:programmingLanguage"])} · licence ${esc(short(id(d["dct:license"])).replace("https://spdx.org/licenses/", ""))}`
      : `${arr(d["dcat:theme"]).map((x) => esc(short(id(x)))).join(", ")} · ${esc(short(id(d["dct:spatial"])))} · ${esc(t["dcat:startDate"])} – ${esc(t["dcat:endDate"])} · modified ${esc(d["dct:modified"])}`;
    const related = [...arr(d["dct:relation"]), ...arr(d["schema:isBasedOn"])].map(id);
    const card = el(`<section class="ds">
      <div class="meta">${meta}</div>
      <h2>${esc(d["dct:title"])}</h2>
      <div>${esc(d["dct:description"]) || "<i>No description</i>"}</div>
      <div class="tags">${arr(d["dcat:keyword"]).map((k) => `<a href="${CAT}/?q=${encodeURIComponent(k)}" title="Search the DigiLab catalogue">${esc(k)}</a>`).join("")}</div>
      ${related.length ? `<h3>Related</h3><div class="meta">${related.map((u) => `<a href="${esc(u)}">${esc(u.replace("https://", ""))}</a>`).join(" · ")}</div>` : ""}
      <h3>Access terms (ODRL offer)</h3>
      ${policyTree(d["odrl:hasPolicy"])}
      <div class="actions">
        ${link ? `<a href="${esc(link)}">${linkText} ↗</a>` : ""}
        <a href="${CAT}/?dataset=${encodeURIComponent(d["@id"])}">View in DigiLab catalogue ↗</a>
        <button class="link">DCAT for this ${sw ? "resource" : "dataset"}</button>
      </div>
      <pre hidden></pre></section>`);
    card.querySelector("button").onclick = () => {
      const p = card.querySelector("pre");
      p.textContent = JSON.stringify({ "@context": raw["@context"], ...d }, null, 2); p.hidden = !p.hidden;
    };
    main.append(card);
  }

  // Is this catalogue harvested by the central DigiLab catalogue?
  try {
    const s = await (await fetch(`${CAT}/api/sources`)).json();
    const st = document.getElementById("status");
    if (s.sources.some((x) => x.id === sourceId)) {
      st.className = "badge ok"; st.innerHTML = `listed in <a href="${CAT}/?source=${sourceId}">DigiLab catalogue</a>`;
    } else {
      st.className = "badge no"; st.innerHTML = `not yet in <a href="${CAT}/#register">DigiLab catalogue</a>`;
    }
  } catch { document.getElementById("status").textContent = "DigiLab catalogue unreachable"; }
})();
