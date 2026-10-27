"""Consulta por cargo e comparação com eleições anteriores.

O ciclo atual vem dos JSON de apuração do TSE. Anos anteriores vêm de
historico.json (votos nominais do dados abertos), quando o arquivo existe.
"""
import json
import os
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import fetch as F
import historico

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
CFG_URL = "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json"
MUN_URL = "https://resultados.tse.jus.br/oficial/ele2024/619/config/mun-e000619-cm.json"

CARGOS = {
    "presidente": {
        "nome": "Presidente", "ambito": "br", "limite": 8,
        "anos": [
            {"ano": 2026, "turno": 2, "ciclo": "ele2026", "ele": "6258", "cargo": "1"},
            {"ano": 2026, "turno": 1, "ciclo": "ele2026", "ele": "6257", "cargo": "1"},
        ],
    },
    "governador": {
        "nome": "Governador", "ambito": "uf", "limite": 10,
        "anos": [
            {"ano": 2026, "turno": 2, "ciclo": "ele2026", "ele": "6260", "cargo": "3"},
            {"ano": 2026, "turno": 1, "ciclo": "ele2026", "ele": "6259", "cargo": "3"},
        ],
    },
    "senador": {
        "nome": "Senador", "ambito": "uf", "limite": 12,
        "anos": [{"ano": 2026, "turno": 1, "ciclo": "ele2026", "ele": "6259", "cargo": "5"}],
    },
    "dep-federal": {
        "nome": "Deputado Federal", "ambito": "uf", "limite": 40,
        "anos": [{"ano": 2026, "turno": 1, "ciclo": "ele2026", "ele": "6259", "cargo": "6"}],
    },
    "dep-estadual": {
        "nome": "Deputado Estadual", "ambito": "uf", "limite": 40,
        "anos": [{"ano": 2026, "turno": 1, "ciclo": "ele2026", "ele": "6259", "cargo": "7", "cargo_df": "8"}],
    },
    "prefeito": {
        "nome": "Prefeito", "ambito": "mu", "limite": 10,
        "anos": [
            {"ano": 2024, "turno": 2, "ciclo": "ele2024", "ele": "620", "cargo": "11"},
            {"ano": 2024, "turno": 1, "ciclo": "ele2024", "ele": "619", "cargo": "11"},
        ],
    },
    "vereador": {
        "nome": "Vereador", "ambito": "mu", "limite": 40,
        "anos": [{"ano": 2024, "turno": 1, "ciclo": "ele2024", "ele": "619", "cargo": "13"}],
    },
}
ANTERIORES = {
    "presidente": (2022, 2018), "governador": (2022, 2018), "senador": (2022, 2018),
    "dep-federal": (2022, 2018), "dep-estadual": (2022, 2018),
    "prefeito": (2020, 2016), "vereador": (2020, 2016),
}
CAPITAIS = {
    "ac": "RIO BRANCO", "al": "MACEIO", "am": "MANAUS", "ap": "MACAPA", "ba": "SALVADOR",
    "ce": "FORTALEZA", "es": "VITORIA", "go": "GOIANIA", "ma": "SAO LUIS",
    "mg": "BELO HORIZONTE", "ms": "CAMPO GRANDE", "mt": "CUIABA", "pa": "BELEM",
    "pb": "JOAO PESSOA", "pe": "RECIFE", "pi": "TERESINA", "pr": "CURITIBA",
    "rj": "RIO DE JANEIRO", "rn": "NATAL", "ro": "PORTO VELHO", "rr": "BOA VISTA",
    "rs": "PORTO ALEGRE", "sc": "FLORIANOPOLIS", "se": "ARACAJU", "sp": "SAO PAULO",
    "to": "PALMAS",
}
GOV2_FALLBACK = {"ac", "am", "df", "es", "rn", "to"}
LOCK = threading.Lock()
_CFG = None
_MUNS = None


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def spec_de(cargo):
    return CARGOS.get(cargo) or CARGOS["presidente"]


def ano_de(spec, turno):
    for item in spec["anos"]:
        if item["turno"] == turno:
            return item
    return spec["anos"][0]


def cargo_codigo(item, abr):
    if abr == "df" and item.get("cargo_df"):
        return item["cargo_df"]
    return item["cargo"]


def hist_id(cargo, uf):
    if cargo == "dep-estadual" and (uf or "").upper() == "DF":
        return "dep-distrital"
    return cargo


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _ler(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _gravar(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)


def config():
    global _CFG
    if _CFG:
        return _CFG
    path = os.path.join(CACHE, "ele-c.json")
    try:
        if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 12 * 3600:
            _gravar(path, _get(CFG_URL))
        cfg = _ler(path)
    except Exception:
        cfg = _ler(path) if os.path.exists(path) else None
    gov, pref = set(GOV2_FALLBACK), {}
    if cfg:
        for pl in cfg.get("pl") or []:
            for e in pl.get("e") or []:
                if str(e.get("cd")) == "6260":
                    gov = {a.get("cd", "").lower() for a in e.get("abr") or [] if a.get("cd")}
                elif str(e.get("cd")) == "620":
                    for a in e.get("abr") or []:
                        uf = (a.get("cd") or "").lower()
                        if not uf:
                            continue
                        pref[uf] = {(m.get("cd") or "").zfill(5) for m in a.get("mu") or []}
    _CFG = {"gov": gov, "pref": pref}
    return _CFG


def municipios(uf):
    global _MUNS
    if _MUNS is None:
        path = os.path.join(CACHE, "mun-2024.json")
        try:
            if not os.path.exists(path):
                _gravar(path, _get(MUN_URL))
            doc = _ler(path)
        except Exception:
            doc = _ler(path) if os.path.exists(path) else {"abr": []}
        muns = {}
        for a in doc.get("abr") or []:
            cd = (a.get("cd") or "").lower()
            muns[cd] = sorted(
                ({"cd": (m.get("cd") or "").zfill(5), "nome": m.get("nm") or ""} for m in a.get("mu") or []),
                key=lambda m: fold(m["nome"]),
            )
        _MUNS = muns
    return _MUNS.get((uf or "").lower(), [])


def capital(uf):
    alvo = CAPITAIS.get((uf or "").lower())
    if not alvo:
        return ""
    for m in municipios(uf):
        if fold(m["nome"]) == alvo:
            return m["cd"]
    return ""


def cortar(cands, limite):
    if not limite or len(cands) <= limite:
        return cands
    top = list(cands[:limite])
    ids = {c["num"] for c in top}
    top.extend(c for c in cands[limite:] if c.get("eleito") and c["num"] not in ids)
    return top


def _cache_path(url):
    nome = url.rstrip("/").split("/")[-1]
    return os.path.join(CACHE, "tse", nome)


def carregar(item, abr, mun=""):
    abr = (abr or "").lower()
    mun = (mun or "").zfill(5) if mun else ""
    url = F.arquivo(item["ciclo"], item["ele"], cargo_codigo(item, abr), abr, mun)
    path = _cache_path(url)
    miss = path + ".miss"
    with LOCK:
        if os.path.exists(path):
            idade = time.time() - os.path.getmtime(path)
            doc = _ler(path)
            if doc.get("totalizacao_final") or idade < 60:
                return doc
        elif os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 6 * 3600:
            return None
    try:
        parsed = F.parse(F.baixar(url))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            os.makedirs(os.path.dirname(miss), exist_ok=True)
            open(miss, "w", encoding="utf-8").write("404")
            return None
        raise
    parsed["candidatos"] = cortar(parsed["candidatos"], 80)
    parsed["base"] = "validos"
    with LOCK:
        _gravar(path, parsed)
    return parsed


def vivo_geo(data, abr):
    if not data:
        return None
    if abr in ("", "br"):
        return data.get("br")
    uf = abr.upper()
    for u in data.get("ufs") or []:
        if u.get("uf") == uf:
            return {k: v for k, v in u.items() if k not in ("uf", "nome")}
    return None


def linha_json(parsed, ano, turno):
    if not parsed:
        return None
    return {
        "ano": ano, "turno": turno, "rotulo": f"{ano} · {turno}º turno",
        "base": "validos", "pct_apurado": parsed.get("pct_apurado"),
        "candidatos": cortar(parsed.get("candidatos") or [], 4),
    }


def anos_do(cargo):
    vistos = []
    for item in CARGOS[cargo]["anos"]:
        if item["ano"] not in vistos:
            vistos.append(item["ano"])
    for ano in ANTERIORES.get(cargo, ()):
        if ano not in vistos:
            vistos.append(ano)
    return vistos


def ao_vivo(spec, ano):
    return any(item["ano"] == ano for item in spec["anos"])


def resultado_hist(row):
    if not row:
        return None
    return {
        "pct_apurado": 100, "totalizacao_final": True, "base": "nominais",
        "candidatos": row.get("candidatos") or [], "nominais": row.get("nominais") or 0,
    }


def uma(cargo, spec, ano, turno, uf, mun):
    """Uma linha de comparação para um ano e um turno, ou None."""
    item = next((a for a in spec["anos"] if a["ano"] == ano and a["turno"] == turno), None)
    if item:
        if turno == 2 and not permite(cargo, 2, uf, mun):
            return None
        abr = "br" if spec["ambito"] == "br" and not uf else uf
        try:
            parsed = carregar(item, abr or "br", mun if spec["ambito"] == "mu" else "")
        except Exception:
            parsed = None
        return linha_json(parsed, ano, turno)
    geo = "" if spec["ambito"] == "br" and not uf else uf
    return historico.linha(hist_id(cargo, geo), ano, turno, geo, mun if spec["ambito"] == "mu" else "")


def comparacao(cargo, spec, ano, turno, uf, mun):
    linhas = []
    for t in (2, 1):
        if t == turno:
            continue
        row = uma(cargo, spec, ano, t, uf, mun)
        if row:
            linhas.append(row)
    for outro in anos_do(cargo):
        if outro == ano:
            continue
        row = uma(cargo, spec, outro, turno, uf, mun) or uma(cargo, spec, outro, 1 if turno == 2 else 2, uf, mun)
        if row:
            linhas.append(row)
    return linhas


def mapa_hist(cargo, ano, turno, incluir_zz):
    ufs = [u for u in F.UFS if u != "zz" or incluir_zz]
    saida = []
    for uf in ufs:
        if uf == "zz" and cargo != "presidente":
            continue
        hid = hist_id(cargo, uf)
        bloco = (historico.nodo(hid, ano, turno) or {}).get(uf.upper())
        if not isinstance(bloco, dict) or "candidatos" not in bloco:
            saida.append({"uf": uf.upper(), "nome": F.NOMES[uf], "candidatos": [], "pct_apurado": None, "sem": turno == 2})
            continue
        saida.append({
            "uf": uf.upper(), "nome": F.NOMES[uf], "sem": False, "pct_apurado": 100,
            "eleitorado": bloco.get("nominais") or 0, "base": "nominais",
            "candidatos": (bloco.get("candidatos") or [])[:2],
        })
    return saida


def permite(cargo, turno, uf, mun):
    if turno != 2:
        return True
    cfg = config()
    if cargo == "governador":
        return (uf or "").lower() in cfg["gov"]
    if cargo == "prefeito":
        return (mun or "").zfill(5) in (cfg["pref"].get((uf or "").lower()) or set())
    return cargo == "presidente"


def mapa(spec, item, incluir_zz, filtrar_turno2=False):
    ufs = [u for u in F.UFS if u != "zz" or incluir_zz]
    buscar = []
    saida = {}
    for uf in ufs:
        if item["turno"] == 2 and filtrar_turno2 and uf not in config()["gov"]:
            saida[uf] = {"uf": uf.upper(), "nome": F.NOMES[uf], "candidatos": [], "pct_apurado": None, "secoes_tot": 0, "sem": True}
            continue
        if uf == "zz" and spec["nome"] != "Presidente":
            continue
        buscar.append(uf)
    if buscar:
        with ThreadPoolExecutor(8) as ex:
            futs = {ex.submit(carregar, item, uf): uf for uf in buscar}
            for fut in as_completed(futs):
                uf = futs[fut]
                try:
                    parsed = fut.result()
                except Exception:
                    parsed = None
                if not parsed:
                    saida[uf] = {"uf": uf.upper(), "nome": F.NOMES[uf], "candidatos": [], "pct_apurado": None, "secoes_tot": 0}
                    continue
                saida[uf] = {
                    "uf": uf.upper(), "nome": F.NOMES[uf], "sem": False,
                    "pct_apurado": parsed.get("pct_apurado"), "secoes_tot": parsed.get("secoes_tot") or 0,
                    "eleitorado": parsed.get("eleitorado") or 0,
                    "candidatos": cortar(parsed.get("candidatos") or [], 2),
                }
    return [saida[u] for u in ufs if u in saida]


def responder(cargo, turno, ano, uf, mun, com_mapa, vivo=None):
    cargo = cargo if cargo in CARGOS else "presidente"
    spec = CARGOS[cargo]
    disponiveis = anos_do(cargo)
    try:
        turno = int(turno or 0)
    except ValueError:
        turno = 0
    try:
        ano = int(ano or 0)
    except ValueError:
        ano = 0
    if ano not in disponiveis:
        ano = disponiveis[0]
    if turno not in {a["turno"] for a in spec["anos"]}:
        turno = spec["anos"][0]["turno"]
    uf = (uf or "").lower()
    mun = (mun or "").strip()
    nota = ""
    nome = spec["nome"]
    if cargo == "dep-estadual" and uf == "df":
        nome = "Deputado Distrital"
    if spec["ambito"] == "mu" and uf == "df":
        return _base(cargo, spec, nome, turno, ano, uf, "", "O Distrito Federal não elege prefeito nem vereador.")
    if spec["ambito"] in ("uf", "mu") and not uf:
        uf = "sp"
    if spec["ambito"] == "mu" and uf and not mun:
        mun = capital(uf)
    passado = not ao_vivo(spec, ano)
    if turno == 2 and not passado and not permite(cargo, 2, uf, mun):
        turno = 1
        nota = "Não houve 2º turno nesta disputa. Mostrando o 1º turno."
    if turno == 2 and passado and not uma(cargo, spec, ano, 2, uf, mun):
        turno = 1
        nota = "Não houve 2º turno nesta disputa em " + str(ano) + ". Mostrando o 1º turno."
    item = next((a for a in spec["anos"] if a["ano"] == ano and a["turno"] == turno), None)
    abr = "br" if spec["ambito"] == "br" and not uf else uf
    mun_arq = mun if spec["ambito"] == "mu" else ""
    data_vivo = None
    extra = {}
    if vivo and cargo == "presidente" and item and item["ele"] == "6258":
        data_vivo, extra = vivo()
    try:
        if passado:
            geo = "" if spec["ambito"] == "br" and not uf else uf
            parsed = resultado_hist(historico.linha(hist_id(cargo, geo), ano, turno, geo, mun_arq))
        else:
            parsed = vivo_geo(data_vivo, abr) if data_vivo else None
            if parsed is None and item:
                parsed = carregar(item, abr or "br", mun_arq)
    except Exception as e:
        return _base(cargo, spec, nome, turno, ano, uf, mun, "", erro=f"{type(e).__name__}: {e}")
    if parsed is None and not nota:
        nota = "Não há resultado desse ano para esta disputa."
    if parsed:
        parsed = dict(parsed)
        parsed["candidatos"] = cortar(parsed.get("candidatos") or [], spec["limite"])
    foco = parsed
    br = None
    if cargo == "presidente":
        if passado:
            br = resultado_hist(historico.linha("presidente", ano, turno, "", ""))
        elif data_vivo and item and item["ele"] == "6258":
            br = data_vivo.get("br")
        elif not uf:
            br = parsed
        else:
            try:
                br = carregar(item, "br") if item else None
            except Exception:
                br = None
    ufs = None
    if com_mapa:
        if passado and spec["ambito"] != "mu":
            ufs = mapa_hist(cargo, ano, turno, cargo == "presidente")
        elif data_vivo and item and item["ele"] == "6258":
            ufs = data_vivo.get("ufs") or []
        elif spec["ambito"] == "mu":
            ufs = [{"uf": u.upper(), "nome": F.NOMES[u], "candidatos": [], "pct_apurado": None, "secoes_tot": 0} for u in F.UFS if u != "zz"]
        elif item:
            ufs = mapa(spec, item, cargo == "presidente", cargo == "governador")
    lugar = "Brasil"
    mun_nome = ""
    if spec["ambito"] != "br" or uf:
        lugar = F.NOMES.get(uf, uf.upper())
    if spec["ambito"] == "mu" and mun:
        for m in municipios(uf):
            if m["cd"] == mun.zfill(5):
                mun_nome = m["nome"]
                lugar = f"{mun_nome} ({uf.upper()})"
                break
    comp_uf = uf if spec["ambito"] != "br" or uf else ""
    comp_mun = mun if spec["ambito"] == "mu" else ""
    try:
        comp = comparacao(cargo, spec, ano, turno, comp_uf, comp_mun)
    except Exception:
        comp = []
    out = _base(cargo, spec, nome, turno, ano, uf, mun, nota)
    out.update({
        "ano": ano, "lugar": lugar, "mun_nome": mun_nome,
        "br": br, "foco": foco, "comparacao": comp,
        "capital": capital(uf) if spec["ambito"] == "mu" else "",
        "municipios": municipios(uf) if spec["ambito"] == "mu" and uf else None,
        "ok_at": extra.get("ok_at"), "fetched_at": extra.get("fetched_at"),
        "hora_changed_at": extra.get("hora_changed_at") if cargo == "presidente" and item and item["ele"] == "6258" else None,
        "error": extra.get("error") if cargo == "presidente" and item and item["ele"] == "6258" else None,
    })
    if ufs is not None:
        out["ufs"] = ufs
    return out


def _base(cargo, spec, nome, turno, ano, uf, mun, nota, erro=None):
    cfg = config()
    return {
        "cargo": cargo, "nome": nome, "ambito": spec["ambito"], "turno": turno, "ano": ano,
        "anos": anos_do(cargo),
        "uf": (uf or "").upper(), "mun": (mun or "").zfill(5) if mun else "",
        "turnos": [a["turno"] for a in spec["anos"]],
        "turno2_ufs": sorted(u.upper() for u in cfg["gov"]) if cargo == "governador" else [],
        "nota": nota, "error": erro, "server_time": time.time(), "poll_s": 30,
        "br": None, "foco": None, "comparacao": [], "ufs": None,
    }
