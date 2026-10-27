import csv
import io
import os
import zipfile
from collections import Counter

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "zips", "2022.zip")
with zipfile.ZipFile(path) as zf:
    with zf.open("votacao_candidato_munzona_2022_SP.csv") as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")
        header = next(reader)
        idx = {h.strip().upper(): i for i, h in enumerate(header)}
        cargo = Counter()
        n = 0
        for row in reader:
            n += 1
            cargo[row[idx["CD_CARGO"]]] += 1
        print("linhas", n)
        print("cargo", cargo)
