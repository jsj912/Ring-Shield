import hashlib, pathlib
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
files = [
    "data/raw/elliptic/elliptic_txs_features.csv",
    "data/raw/elliptic/elliptic_txs_classes.csv",
    "data/raw/elliptic/elliptic_txs_edgelist.csv",
    "data/raw/amlworld/HI-Small_Trans.csv",
    "data/raw/amlworld/HI-Small_Patterns.txt",
]
for f in files:
    print(f, sha256_of(f))