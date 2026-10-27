#!/usr/bin/env python3
"""Site local da apuração — Presidente 2026, 2º turno.

  python3 server.py
  python3 server.py --port 9000
  PORT=9000 python3 server.py

Consulta o TSE a cada 30s. /api/consulta cobre os outros cargos e a
comparação com anos anteriores. Com X_BEARER_TOKEN, atualiza posts.json a cada 5 min
pelas consultas de POSTS_QUERIES.md. Sem o token, serve o recorte posts.sample.json.
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import concurrent.futures as cf
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import consulta
import fetch as F
import merge_posts

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
MAP = os.path.join(HERE, "geo", "map.json")
POSTS = os.path.join(HERE, "posts.json")
SAMPLE = os.path.join(HERE, "posts.sample.json")
QUERIES = os.path.join(HERE, "POSTS_QUERIES.md")
LAST_PATH = os.path.join(HERE, "last_data.json")
POLL = 30
POLL_X = 300
NOTE_OFF = "feed do X desativado — defina X_BEARER_TOKEN"
X_URL = "https://api.x.com/2/tweets/search/recent"

FALLBACK = [
    ("imprensa", "(from:g1 OR from:folha OR from:Estadao OR from:CNNBrasil OR from:JornalOGlobo OR from:UOLNoticias OR from:BandJornalismo OR from:metropoles OR from:TSEjusbr OR from:GloboNews) -is:retweet -is:reply"),
    ("politicos", "(from:LulaOficial OR from:FlavioBolsonaro OR from:jairbolsonaro OR from:gleisi OR from:tarcisiogdf OR from:padilhando OR from:Haddad_Fernando OR from:nikolas_dm OR from:geraldoalckmin) -is:retweet -is:reply"),
    ("politicos", "(from:GuilhermeBoulos OR from:CarlosBolsonaro OR from:BolsonaroSP OR from:romeuzema) -is:retweet -is:reply"),
]

STATE = {"data": None, "fetched_at": None, "ok_at": None, "error": None, "hora_changed_at": None}
LOCK = threading.Lock()
XSTATE = {"ok_at": None, "error": None}
XLOCK = threading.Lock()


def resolve_port(argv):
    p = argparse.ArgumentParser(prog="server.py", description="Apuração ao vivo do 2º turno (TSE 2026)")
    p.add_argument("--port", type=int, default=None)
    args = p.parse_args(argv)
    if args.port is not None:
        return args.port
    env = os.environ.get("PORT", "").strip()
    if env:
        return int(env)
    return 8765


def coleta():
    br = F.parse(F.get("br"))
    ufs = {}
    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(F.get, u): u for u in F.UFS}
        for fut in cf.as_completed(futs):
            uf = futs[fut]
            try:
                ufs[uf] = F.parse(fut.result())
            except Exception as err:
                print(f"aviso: {uf} falhou: {err}", file=sys.stderr)
    return {
        "fonte": F.url("br"),
        "br": br,
        "ufs": [dict(uf=u.upper(), nome=F.NOMES[u], **ufs[u]) for u in F.UFS if u in ufs],
    }


def loop():
    while True:
        now = time.time()
        try:
            new = coleta()
            with LOCK:
                old = STATE["data"]
                if old:
                    got = {u["uf"] for u in new["ufs"]}
                    new["ufs"] += [u for u in old["ufs"] if u["uf"] not in got]
                    order = [x.upper() for x in F.UFS]
                    new["ufs"].sort(key=lambda u: order.index(u["uf"]))
                key = new["br"]["data"] + new["br"]["hora"]
                if not old or old["br"]["data"] + old["br"]["hora"] != key:
                    STATE["hora_changed_at"] = now
                STATE.update(data=new, ok_at=now, error=None)
                hora = STATE["hora_changed_at"]
            tmp = LAST_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"data": new, "hora_changed_at": hora, "ok_at": now}, f, ensure_ascii=False)
            os.replace(tmp, LAST_PATH)
            b = new["br"]
            print(f"TSE {b['data']} {b['hora']} · {b['pct_apurado']:.2f}%", flush=True)
        except Exception as e:
            with LOCK:
                STATE["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        with LOCK:
            STATE["fetched_at"] = now
        time.sleep(max(5, POLL - (time.time() - now)))


def load_queries(path=QUERIES):
    cat = None
    found = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return list(FALLBACK)
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            h = s.lstrip("#").strip().lower()
            if h.startswith("imprensa"):
                cat = "imprensa"
            elif h.startswith("polit"):
                cat = "politicos"
            else:
                cat = None
            continue
        if cat and s.startswith("("):
            found.append((cat, re.sub(r"\s+since:\S+", "", s).strip()))
    return found or list(FALLBACK)


def with_since(query, now=None):
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=30)).strftime("%Y-%m-%d_%H:%M:%S_UTC")
    query = re.sub(r"\s+since:\S+", "", query).strip()
    return f"{query} since:{since}"


def search_recent(token, query):
    params = urllib.parse.urlencode({
        "query": query,
        "max_results": "25",
        "expansions": "author_id",
        "user.fields": "name,username",
        "tweet.fields": "created_at,public_metrics",
    })
    req = urllib.request.Request(
        X_URL + "?" + params,
        headers={
            "Authorization": "Bearer " + token,
            "User-Agent": "apuracao-presidente-2026",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"X HTTP {e.code}: {body}") from None


def refresh_posts(token):
    new = []
    errors = []
    queries = load_queries()
    for i, (cat, q) in enumerate(queries):
        if i:
            time.sleep(1)
        try:
            new.extend(merge_posts.posts_from_payload(search_recent(token, with_since(q)), cat))
        except Exception as e:
            errors.append(str(e))
            print(f"aviso: busca {cat} falhou: {e}", file=sys.stderr)
    if errors and len(errors) == len(queries):
        with XLOCK:
            XSTATE["error"] = errors[0][:300]
        return
    doc = merge_posts.merge_doc(merge_posts.read_posts(POSTS), new)
    merge_posts.write_doc(POSTS, doc)
    with XLOCK:
        XSTATE["ok_at"] = time.time()
        XSTATE["error"] = "; ".join(errors)[:300] if errors else None
    print(f"X: {len(doc['posts'])} posts", flush=True)


def loop_x():
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        print(NOTE_OFF, flush=True)
        return
    print("X: buscando posts a cada 5 min", flush=True)
    while True:
        now = time.time()
        try:
            refresh_posts(token)
        except Exception as e:
            with XLOCK:
                XSTATE["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        time.sleep(max(5, POLL_X - (time.time() - now)))


def ensure_posts():
    if os.path.exists(POSTS):
        return
    if os.path.exists(SAMPLE):
        shutil.copyfile(SAMPLE, POSTS)
        print("posts.json criado a partir de posts.sample.json", flush=True)


def vivo_presidente():
    with LOCK:
        return STATE.get("data"), {
            "ok_at": STATE.get("ok_at"), "fetched_at": STATE.get("fetched_at"),
            "error": STATE.get("error"), "hora_changed_at": STATE.get("hora_changed_at"),
        }


def consulta_resposta(q):
    def primeiro(chave, padrao=""):
        return (q.get(chave) or [padrao])[0]

    return consulta.responder(
        primeiro("cargo", "presidente"), primeiro("turno", "0"), primeiro("ano", "0"),
        primeiro("uf"), primeiro("mun"), primeiro("mapa", "1") != "0", vivo_presidente,
    )


def payload():
    with LOCK:
        s = dict(STATE)
    return {
        "server_time": time.time(),
        "fetched_at": s["fetched_at"],
        "ok_at": s["ok_at"],
        "error": s["error"],
        "hora_changed_at": s["hora_changed_at"],
        "poll_s": POLL,
        **(s["data"] or {"br": None, "ufs": []}),
    }


def posts_body():
    try:
        with open(POSTS, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("posts")
    except Exception:
        data = {"updated_at": None, "posts": []}
    data.setdefault("posts", [])
    if not os.environ.get("X_BEARER_TOKEN", "").strip():
        data["note"] = NOTE_OFF
        data["x_live"] = False
    else:
        data["x_live"] = True
    return json.dumps(data, ensure_ascii=False)


def page():
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    with open(MAP, encoding="utf-8") as f:
        mapa = f.read()
    return html.replace("/*__MAPA__*/null", mapa)


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                self.send(200, page(), "text/html; charset=utf-8")
            elif path == "/api/data":
                self.send(200, json.dumps(payload(), ensure_ascii=False), "application/json; charset=utf-8")
            elif path == "/api/consulta":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self.send(200, json.dumps(consulta_resposta(q), ensure_ascii=False), "application/json; charset=utf-8")
            elif path == "/api/posts":
                self.send(200, posts_body(), "application/json; charset=utf-8")
            elif path == "/healthz":
                self.send(200, "ok", "text/plain; charset=utf-8")
            else:
                self.send(404, "not found", "text/plain; charset=utf-8")
        except Exception as e:
            traceback.print_exc()
            msg = f"{type(e).__name__}: {e}"
            if path == "/api/consulta":
                self.send(500, json.dumps({"error": msg}, ensure_ascii=False), "application/json; charset=utf-8")
            else:
                self.send(500, msg, "text/plain; charset=utf-8")

    def log_message(self, *a):
        pass


def load_last():
    if not os.path.exists(LAST_PATH):
        return
    try:
        with open(LAST_PATH, encoding="utf-8") as f:
            d = json.load(f)
        STATE.update(data=d.get("data"), hora_changed_at=d.get("hora_changed_at"), ok_at=d.get("ok_at") or os.path.getmtime(LAST_PATH))
    except Exception:
        pass


def main():
    port = resolve_port(sys.argv[1:])
    ensure_posts()
    load_last()
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=loop_x, daemon=True).start()
    print("Apuração Presidente 2026 · 2º turno", flush=True)
    print(f"Abra http://localhost:{port}", flush=True)
    print("TSE: atualização a cada 30s", flush=True)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), H)
    except OSError as e:
        print(f"Não foi possível usar a porta {port}: {e}", file=sys.stderr)
        print("Se ela já está em uso: python3 server.py --port 8766", file=sys.stderr)
        sys.exit(1)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando", flush=True)


if __name__ == "__main__":
    main()
