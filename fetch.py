#!/usr/bin/env python3
"""Leitura dos arquivos oficiais do TSE — Presidente 2026, 2º turno (eleição 6258).

Nacional:
  https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json
Por UF (sigla minúscula; zz = Exterior):
  .../dados/<uf>/<uf>-c0001-e006258-u.json

O servidor usa UFS, NOMES, get e parse. `python3 fetch.py` só imprime o total
nacional, para testar se o TSE responde.
"""
import json
import os
import sys
import urllib.request

ELE = os.environ.get("TSE_ELE", "6258")
BASE = f"https://resultados.tse.jus.br/oficial/ele2026/{ELE}/dados"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe", "pi", "pr",
       "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]
NOMES = {
    "ac": "Acre", "al": "Alagoas", "am": "Amazonas", "ap": "Amapá", "ba": "Bahia", "ce": "Ceará",
    "df": "Distrito Federal", "es": "Espírito Santo", "go": "Goiás", "ma": "Maranhão", "mg": "Minas Gerais",
    "ms": "Mato Grosso do Sul", "mt": "Mato Grosso", "pa": "Pará", "pb": "Paraíba", "pe": "Pernambuco",
    "pi": "Piauí", "pr": "Paraná", "rj": "Rio de Janeiro", "rn": "Rio Grande do Norte", "ro": "Rondônia",
    "rr": "Roraima", "rs": "Rio Grande do Sul", "sc": "Santa Catarina", "se": "Sergipe", "sp": "São Paulo",
    "to": "Tocantins", "zz": "Exterior",
}


def url(ab):
    return f"{BASE}/{ab}/{ab}-c0001-e{int(ELE):06d}-u.json"


def get(ab):
    req = urllib.request.Request(url(ab), headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def num(s):
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return 0.0


def parse(d):
    cands = []
    for cg in d["carg"]:
        for agr in cg["agr"]:
            for p in agr["par"]:
                for c in p["cand"]:
                    cands.append({
                        "num": c["n"], "nome": c["nmu"], "partido": p["sg"], "seq": int(c.get("seq") or 99),
                        "votos": int(c["vap"] or 0), "pct": num(c["pvapn"]), "eleito": c.get("e") == "s",
                        "situacao": c.get("st", ""), "vice": (c.get("vs") or [{}])[0].get("nmu", ""),
                    })
    cands.sort(key=lambda c: (-c["votos"], c["seq"]))
    s, e, v = d["s"], d["e"], d["v"]
    return {
        "data": d["dg"], "hora": d["hg"], "totalizacao_final": d.get("tf") == "s",
        "secoes_total": int(s["ts"]), "secoes_tot": int(s["st"]), "pct_apurado": num(s["pstn"]),
        "eleitorado": int(e["te"]), "comparecimento": int(e["c"]), "pct_comparecimento": num(e["pcn"]),
        "abstencao": int(e["a"]), "pct_abstencao": num(e["pan"]),
        "validos": int(v["vv"]), "brancos": int(v["vb"]), "pct_brancos": num(v["pvbn"]),
        "nulos": int(v["tvn"]), "pct_nulos": num(v["ptvnn"]), "candidatos": cands,
    }


def main():
    br = parse(get("br"))
    print(f"TSE {br['data']} {br['hora']} (Brasília) · {br['pct_apurado']:.2f}% das seções")
    for c in br["candidatos"]:
        print(f"  {c['nome']} ({c['partido']} {c['num']}): {c['votos']} votos · {c['pct']:.2f}%")
    print(f"  brancos {br['pct_brancos']:.2f}% · nulos {br['pct_nulos']:.2f}% · abstenção {br['pct_abstencao']:.2f}%")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"não consegui ler o TSE: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
