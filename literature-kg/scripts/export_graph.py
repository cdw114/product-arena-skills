#!/usr/bin/env python3
"""Export the graph to a readable, round-trippable file (GraphML / JSON / Cypher / Mermaid / DOT).

Usage:
  python scripts/export_graph.py --graph graph.aligned.json --format graphml|json|cypher|mermaid|dot \
         --out /app/output/graph.<ext>

Evidence anchors travel as attributes: node keys `sources`, `paragraph_ids`, `first_seen`, `merge_basis`;
edge keys `sources`, `paragraph_ids`, `conditions`, `evidence_strength`. Quotes are kept in JSON/GraphML
(`quotes` attribute, joined with ' || ') so the exported file alone lets a reviewer go back to the text.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_common import load_graph, evidence_sources  # noqa: E402


def _esc(s):
    return (str(s).replace("\\", "\\\\").replace('"', '\\"'))


def to_graphml(g):
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for kid, name, typ in [("n_type", "type", "string"), ("n_name", "canonical_name", "string"), ("n_aliases", "aliases", "string"),
                           ("n_sources", "sources", "string"), ("n_pids", "paragraph_ids", "string"), ("n_quotes", "quotes", "string"),
                           ("n_first", "first_seen", "string"), ("n_merge", "merge_basis", "string"), ("n_conf", "confidence", "string"),
                           ("e_type", "type", "string"), ("e_sources", "sources", "string"), ("e_pids", "paragraph_ids", "string"),
                           ("e_quotes", "quotes", "string"), ("e_cond", "conditions", "string"), ("e_strength", "evidence_strength", "string"),
                           ("e_cross", "cross_paper", "string")]:
        k = ET.SubElement(root, "key", id=kid, **{"for": "node" if kid.startswith("n_") else "edge", "attr.name": name, "attr.type": typ})
    graph = ET.SubElement(root, "graph", id="kg", edgedefault="directed")
    for n in g["nodes"]:
        node = ET.SubElement(graph, "node", id=n["id"])
        d = {"n_type": n["type"], "n_name": n["canonical_name"], "n_aliases": " | ".join(n.get("aliases", [])),
             "n_sources": ",".join(evidence_sources(n)), "n_pids": ",".join(sorted({e["paragraph_id"] for e in n.get("evidence", [])})),
             "n_quotes": " || ".join(e["quote"] for e in n.get("evidence", [])), "n_first": n.get("first_seen", ""),
             "n_merge": ",".join(n.get("merge_basis", [])), "n_conf": n.get("confidence", "")}
        for k, v in d.items():
            ET.SubElement(node, "data", key=k).text = v
    for e in g["edges"]:
        ed = ET.SubElement(graph, "edge", id=e["id"], source=e["src"], target=e["dst"])
        d = {"e_type": e["type"], "e_sources": ",".join(evidence_sources(e)), "e_pids": ",".join(sorted({x["paragraph_id"] for x in e.get("evidence", [])})),
             "e_quotes": " || ".join(x["quote"] for x in e.get("evidence", [])), "e_cond": e.get("conditions", ""),
             "e_strength": e.get("evidence_strength", ""), "e_cross": str(bool(e.get("cross_paper")))}
        for k, v in d.items():
            ET.SubElement(ed, "data", key=k).text = v
    return minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")


def to_cypher(g):
    lines = []
    for n in g["nodes"]:
        lines.append(f"MERGE ({_esc(n['id']).replace('-', '_')}:`{n['type']}` {{id: \"{n['id']}\", name: \"{_esc(n['canonical_name'])}\", "
                     f"sources: \"{','.join(evidence_sources(n))}\", paragraph_ids: \"{','.join(sorted({e['paragraph_id'] for e in n.get('evidence', [])}))}\", "
                     f"quotes: {_esc(json.dumps([e['quote'] for e in n.get('evidence', [])], ensure_ascii=False))[:2000]}}})")
    for e in g["edges"]:
        s = _esc(e['src']).replace('-', '_'); d = _esc(e['dst']).replace('-', '_')
        lines.append(f"MERGE ({s})-[:`{e['type']}` {{id: \"{e['id']}\", sources: \"{','.join(evidence_sources(e))}\", "
                     f"paragraph_ids: \"{','.join(sorted({x['paragraph_id'] for x in e.get('evidence', [])}))}\", conditions: \"{_esc(e.get('conditions', ''))}\"}}]->({d})")
    return "\n".join(lines) + "\n"


def to_mermaid(g):
    out = ["graph LR"]
    for n in g["nodes"]:
        lbl = n["canonical_name"].replace('"', "'").replace("[", "(").replace("]", ")")[:40]
        out.append(f"  {node_mid(n['id'])}[\"{lbl}<br/>{n['type']} · {','.join(evidence_sources(n))}\"]")
    for e in g["edges"]:
        out.append(f"  {node_mid(e['src'])} -->|{e['type']}| {node_mid(e['dst'])}")
    return "\n".join(out) + "\n"


def to_dot(g):
    out = ["digraph kg {", "  rankdir=LR;", '  node [shape=box, style="rounded,filled", fillcolor="#eef", fontsize=10];']
    for n in g["nodes"]:
        lbl = n["canonical_name"].replace('"', '\\"')[:35]
        out.append(f'  "{n["id"]}" [label="{lbl}\\n{n["type"]} · {len(evidence_sources(n))}src"];')
    for e in g["edges"]:
        out.append(f'  "{e["src"]}" -> "{e["dst"]}" [label="{e["type"]}"];')
    out.append("}")
    return "\n".join(out) + "\n"


def node_mid(i):
    return "n_" + "".join(c if c.isalnum() else "_" for c in i)


def to_json(g):
    return json.dumps(g, ensure_ascii=False, indent=2) + "\n"


EXT = {"graphml": "graphml", "json": "json", "cypher": "cypher", "mermaid": "mmd", "dot": "dot"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--format", required=True, choices=sorted(EXT))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    g = load_graph(a.graph)
    txt = {"graphml": to_graphml, "json": to_json, "cypher": to_cypher, "mermaid": to_mermaid, "dot": to_dot}[a.format](g)
    out = Path(a.out) if a.out else Path(a.graph).with_suffix("." + EXT[a.format])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    print(json.dumps({"written": str(out), "format": a.format, "nodes": len(g["nodes"]), "edges": len(g["edges"]), "bytes": len(txt.encode('utf-8'))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
