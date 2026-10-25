#!/usr/bin/env python3
"""Junta posts do X (resposta do recent search, ou dumps em raw/) em posts.json.

Mantém os posts anteriores, atualiza as métricas, ignora respostas (texto
começando com @), deduplica por id, limita a 4 por autor e guarda os 20
melhores de cada categoria (recência + engajamento).

Categoria de um arquivo em raw/: o nome começa com "polit" → politicos;
qualquer outro → imprensa.

Uso: python3 merge_posts.py [arquivos...]    (padrão: raw/*.txt e raw/*.json)
"""
import glob
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "posts.json")
TOP = int(os.environ.get("TOP", "20"))


def objs(text):
    dec = json.JSONDecoder()
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return
        try:
            o, end = dec.raw_decode(text, j)
            yield o
            i = end
        except ValueError:
            i = j + 1


def posts_from_payload(payload, category):
    """Normaliza um JSON do recent search (data + includes.users)."""
    if not isinstance(payload, dict) or "data" not in payload:
        return []
    users = {}
    for u in ((payload.get("includes") or {}).get("users") or []):
        if isinstance(u, dict) and u.get("id"):
            users[u["id"]] = u
    out = []
    for p in payload.get("data") or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        u = users.get(p.get("author_id")) or {}
        m = p.get("public_metrics") or {}
        un = u.get("username") or ""
        text = p.get("text") or ""
        if text.lstrip().startswith("@"):
            continue
        out.append({
            "id": str(p["id"]),
            "url": p.get("url") or f"https://x.com/{un or 'i'}/status/{p['id']}",
            "author_name": u.get("name") or un,
            "username": un,
            "verified": bool(u.get("verified")),
            "created_at": p.get("created_at"),
            "text": text,
            "likes": m.get("like_count", 0) or 0,
            "reposts": m.get("retweet_count", 0) or 0,
            "replies": m.get("reply_count", 0) or 0,
            "quotes": m.get("quote_count", 0) or 0,
            "views": m.get("impression_count", 0) or 0,
            "category": category,
        })
    return out


def load(path):
    name = os.path.basename(path).lower()
    cat = "politicos" if name.startswith("polit") else "imprensa"
    out = []
    with open(path, encoding="utf-8") as f:
        for d in objs(f.read()):
            out.extend(posts_from_payload(d, cat))
    return out


def score(p, now):
    try:
        age_h = (now - datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    except Exception:
        age_h = 24
    eng = p.get("likes", 0) + 2 * p.get("reposts", 0) + p.get("quotes", 0) + p.get("replies", 0) * 0.5
    return math.log10(1 + eng) - age_h * 0.35  # ~1 ordem de grandeza de engajamento vale ~3h


def read_posts(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        return []
    return [p for p in (doc.get("posts") or []) if isinstance(p, dict)]


def merge_doc(existing, new_posts, top=None):
    top = TOP if top is None else top
    byid = {}
    for p in existing or []:
        text = str(p.get("text") or "")
        if p.get("id") and not text.lstrip().startswith("@"):
            p["id"] = str(p["id"])
            byid[p["id"]] = p
    for p in new_posts or []:
        text = str(p.get("text") or "")
        if not p.get("id") or text.lstrip().startswith("@"):
            continue
        p["id"] = str(p["id"])
        byid[p["id"]] = p
    now = datetime.now(timezone.utc)
    posts = []
    for cat in ("imprensa", "politicos"):
        c = [p for p in byid.values() if p.get("category") == cat]
        c.sort(key=lambda p: -score(p, now))
        per = {}
        keep = []
        for p in c:
            user = p.get("username") or ""
            if per.get(user, 0) >= 4:
                continue
            per[user] = per.get(user, 0) + 1
            keep.append(p)
            if len(keep) >= top:
                break
        posts.extend(keep)
    posts.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return {"updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "posts": posts}


def write_doc(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def main():
    files = sys.argv[1:] or sorted(
        glob.glob(os.path.join(HERE, "raw", "*.txt")) + glob.glob(os.path.join(HERE, "raw", "*.json"))
    )
    new = []
    for f in files:
        new.extend(load(f))
    doc = merge_doc(read_posts(OUT), new)
    write_doc(OUT, doc)
    posts = doc["posts"]
    print(len(posts), Counter(p["category"] for p in posts), Counter(p["username"] for p in posts))


if __name__ == "__main__":
    main()
