#!/usr/bin/env python3
"""Comparação com eleições anteriores, a partir dos ZIP do dados abertos do TSE.

Gera historico.json (votos nominais agregados). Os ZIP ficam em cache/zips e
não entram no git.

  python3 historico.py download
  python3 historico.py build
"""
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ZDIR = os.path.join(HERE, "cache", "zips")
OUT = os.path.join(HERE, "historico.json")

ZIPS = {
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip",
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2018.zip",
    2020: "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2020.zip",
    2016: "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2016.zip",
}
# Códigos de cargo do TSE que esta página compara.
QUER = {
    2022: {"1", "3", "5", "6", "7", "8"},
    2018: {"1", "3", "5", "6", "7", "8"},
    2020: {"11", "13"},
    2016: {"11", "13"},
}
NOME = {
    "1": "presidente", "3": "governador", "5": "senador", "6": "dep-federal",
    "7": "dep-estadual", "8": "dep-distrital", "11": "prefeito", "13": "vereador",
}
MUNICIPAL = {"11", "13"}
TOP = {"11": 4, "13": 3}


def baixar(ano):
    os.makedirs(ZDIR, exist_ok=True)
    dest = os.path.join(ZDIR, f"{ano}.zip")
    url = ZIPS[ano]
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"{ano}: zip já está em cache ({os.path.getsize(dest)} bytes)", flush=True)
        return dest
    tmp = dest + ".part"
    print(f"{ano}: baixando {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "apuracao-eleicoes"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)
            got += len(buf)
            if total and got // (20 << 20) != (got - len(buf)) // (20 << 20):
                print(f"{ano}: {got // (1 << 20)} / {total // (1 << 20)} MiB", flush=True)
    os.replace(tmp, dest)
    print(f"{ano}: salvo {os.path.getsize(dest)} bytes", flush=True)
    return dest


def coluna(header, *nomes):
    idx = {h.strip().upper(): i for i, h in enumerate(header)}
    for nome in nomes:
        if nome in idx:
            return idx[nome]
    return None


def agregar(ano, path):
    quer = QUER[ano]
    acc = {}
    linhas = 0
    with zipfile.ZipFile(path) as zf:
        # O ZIP repete o país inteiro em *_BRASIL.csv (a soma dos arquivos por UF).
        # Somar esse arquivo dobra os votos. O de presidente fica em *_BR.csv.
        nomes = [
            n for n in zf.namelist()
            if n.lower().endswith(".csv") and not n.upper().endswith("_BRASIL.CSV")
        ]
        for nome in nomes:
            with zf.open(nome) as raw:
                texto = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                reader = csv.reader(texto, delimiter=";")
                try:
                    header = next(reader)
                except StopIteration:
                    continue
                i_cargo = coluna(header, "CD_CARGO", "CODIGO_CARGO")
                i_turno = coluna(header, "NR_TURNO", "NUMERO_TURNO")
                i_uf = coluna(header, "SG_UF", "SIGLA_UF")
                i_mun = coluna(header, "CD_MUNICIPIO", "CODIGO_MUNICIPIO")
                i_num = coluna(header, "NR_CANDIDATO", "NUMERO_CANDIDATO")
                i_nome = coluna(header, "NM_URNA_CANDIDATO", "NOME_URNA_CANDIDATO", "NM_CANDIDATO")
                i_part = coluna(header, "SG_PARTIDO", "SIGLA_PARTIDO")
                i_votos = coluna(header, "QT_VOTOS_NOMINAIS", "TOTAL_VOTOS", "QT_VOTOS")
                i_sit = coluna(header, "DS_SIT_TOT_TURNO", "DESC_SIT_TOT_TURNO")
                faltando = [k for k, v in {
                    "cargo": i_cargo, "turno": i_turno, "uf": i_uf, "num": i_num, "votos": i_votos,
                }.items() if v is None]
                if faltando:
                    raise SystemExit(f"{ano} {nome}: colunas ausentes {faltando}; cabeçalho={header[:12]}")
                for row in reader:
                    linhas += 1
                    if linhas % 2_000_000 == 0:
                        print(f"{ano}: {linhas} linhas", flush=True)
                    if i_cargo >= len(row):
                        continue
                    cargo = row[i_cargo].strip()
                    if cargo not in quer:
                        continue
                    try:
                        votos = int((row[i_votos] or "0").strip() or 0)
                    except ValueError:
                        continue
                    turno = row[i_turno].strip()
                    uf = row[i_uf].strip().upper()
                    num = row[i_num].strip()
                    urna = (row[i_nome].strip() if i_nome is not None and i_nome < len(row) else "") or num
                    partido = row[i_part].strip() if i_part is not None and i_part < len(row) else ""
                    sit = row[i_sit].strip() if i_sit is not None and i_sit < len(row) else ""
                    geos = [uf]
                    if cargo == "1":
                        geos.append("BR")
                    if cargo in MUNICIPAL:
                        mun = row[i_mun].strip() if i_mun is not None and i_mun < len(row) else ""
                        if not mun:
                            continue
                        geos = [f"{uf}:{mun.zfill(5)}"]
                    for geo in geos:
                        key = (cargo, turno, geo, num)
                        rec = acc.get(key)
                        if rec is None:
                            acc[key] = [votos, urna, partido, sit]
                        else:
                            rec[0] += votos
                            if sit:
                                rec[3] = sit
    print(f"{ano}: {linhas} linhas, {len(acc)} chaves", flush=True)
    grupos = {}
    for (cargo, turno, geo, num), (votos, urna, partido, sit) in acc.items():
        grupos.setdefault((cargo, turno, geo), []).append((votos, num, urna, partido, sit))
    arvore = {}
    for (cargo, turno, geo), lista in grupos.items():
        lista.sort(key=lambda x: -x[0])
        total = sum(x[0] for x in lista)
        topn = TOP.get(cargo, 5)
        cands = []
        for votos, num, urna, partido, sit in lista[:topn]:
            cands.append({
                "num": num, "nome": urna, "partido": partido, "votos": votos,
                "pct": round(100 * votos / total, 4) if total else 0,
                "situacao": sit, "eleito": sit.upper().startswith("ELEITO"),
            })
        no = arvore.setdefault(NOME[cargo], {}).setdefault(turno, {})
        if ":" in geo:
            uf, mun = geo.split(":", 1)
            no.setdefault(uf, {})[mun] = {"nominais": total, "candidatos": cands}
        else:
            no[geo] = {"nominais": total, "candidatos": cands}
    return arvore


def build():
    anos = {}
    for ano in (2016, 2018, 2020, 2022):
        path = os.path.join(ZDIR, f"{ano}.zip")
        if not os.path.exists(path):
            print(f"{ano}: zip ausente, pulando", flush=True)
            continue
        anos[str(ano)] = agregar(ano, path)
    doc = {
        "fonte": "TSE dados abertos — votacao_candidato_munzona (votos nominais)",
        "anos": anos,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    print(f"gravei {OUT} ({os.path.getsize(OUT)} bytes)", flush=True)


_DOC = None
_MTIME = None


def carregar():
    global _DOC, _MTIME
    try:
        mtime = os.path.getmtime(OUT)
    except OSError:
        return None
    if _DOC is None or _MTIME != mtime:
        with open(OUT, encoding="utf-8") as f:
            _DOC = json.load(f)
        _MTIME = mtime
    return _DOC


def nodo(cargo_id, ano, turno):
    """Mapa do turno: UF → resultado, ou UF → município → resultado."""
    doc = carregar()
    if not doc:
        return {}
    return (((doc.get("anos") or {}).get(str(ano)) or {}).get(cargo_id) or {}).get(str(turno)) or {}


def linha(cargo_id, ano, turno, uf, mun):
    """Um recorte já agregado, ou None."""
    no = nodo(cargo_id, ano, turno)
    if not no:
        return None
    if cargo_id in ("prefeito", "vereador"):
        if not uf or not mun:
            return None
        bloco = (no.get(uf.upper()) or {}).get(str(mun).zfill(5))
    elif cargo_id == "presidente" and not uf:
        bloco = no.get("BR")
    else:
        if not uf:
            return None
        bloco = no.get(uf.upper())
    if not bloco:
        return None
    return {
        "ano": int(ano), "turno": int(turno),
        "rotulo": f"{ano} · {turno}º turno",
        "base": "nominais",
        "pct_apurado": 100,
        "candidatos": bloco.get("candidatos") or [],
        "nominais": bloco.get("nominais") or 0,
    }


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "download":
        for ano in (2016, 2018, 2020, 2022):
            baixar(ano)
    elif cmd == "build":
        build()
    elif cmd == "all":
        for ano in (2016, 2018, 2020, 2022):
            baixar(ano)
        build()
    else:
        raise SystemExit("uso: historico.py download|build|all")


if __name__ == "__main__":
    main()
