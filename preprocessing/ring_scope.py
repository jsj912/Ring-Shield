"""Step 2.2 / 2.3: per-ring scope table, in-scope counts per policy, and the ceiling.

    python preprocessing/ring_scope.py --gt data/processed/amlworld_ring_ground_truth.parquet \
        --splits data/processed --out docs/ring_scope.json

Per ring: n_txn (pattern lines of the ring), n_txn_train/val/test (lines assigned to a split
by timestamp against the split boundaries), frac_test, start/end (loader basis), n_members,
n_banks, pattern_type; plus n_rows_train/val/test = rows of the transaction table labelled
with the ring (duplicate payments make this >= the line count; not used for scope).
Summary, for the test and the validation split, under three policies:
    test_visible  >= 1 pattern line in the split; scored members = accounts on the ring's
                  lines in that split only                                   (PRIMARY)
    strict        all pattern lines in the split; full membership              (appendix)
    majority      > 50 % of pattern lines in the split; full membership        (appendix)
ring count, rings with < 3 (visible) members and their pattern-type breakdown, straddling
count; plus the pattern breakdown of all rings with < 3 members. Ceiling under test_visible:
(a) test laundering transactions, (b) those in an in-scope ring, (c) in-scope-ring members
(full membership) with no test-period transaction. Strict ceiling kept for the appendix.

Policy (recorded in docs/RING_GROUND_TRUTH_DEFINITION.md): test_visible for every reported
number, strict and majority in an appendix, rings with < 3 members stay in the denominator,
Jaccard 0.5 with a sweep at 0.3 and 0.7.

--dry-run keeps a deterministic 1% of rings (at least one, random_state=--seed) and writes
docs/ring_scope_dryrun.json instead.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import bank_of_series, load_account_bank_map, load_paths  # noqa: E402

SPLITS = ["train", "val", "test"]
DRY_RUN_FRAC = 0.01
POLICIES = ["test_visible", "strict", "majority"]
POLICY = {
    "scope_policy": "test_visible",
    "appendix_policies": ["strict", "majority"],
    "test_visible_rule": "n_txn_<split> >= 1; scored members = union(from_id, to_id) over the ring's "
                         "pattern lines in <split> only",
    "strict_rule": "n_txn_<split> == n_txn and n_txn > 0; full membership",
    "majority_rule": "n_txn_<split> / n_txn > 0.5; full membership",
    "scope_unit": "pattern lines (3,209), not matched rows (3,455)",
    "rings_with_lt3_members": "stay in the denominator",
    "jaccard_threshold": 0.5,
    "jaccard_sweep": [0.3, 0.7],
}


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


# --------------------------------------------------------------------------- #
# per-ring table
# --------------------------------------------------------------------------- #
def load_split_labels(splits_dir: Path) -> dict[str, pd.DataFrame]:
    cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering", "ring_id"]
    return {s: pd.read_parquet(splits_dir / f"amlworld_{s}.parquet", columns=cols) for s in SPLITS}


def split_bounds(splits: dict[str, pd.DataFrame]) -> dict[str, tuple[int, int]]:
    """[min, max] Timestamp of each split; asserts they are ordered and non-overlapping."""
    b = {s: (int(df["Timestamp"].min()), int(df["Timestamp"].max())) for s, df in splits.items()}
    assert b["train"][1] < b["val"][0] <= b["val"][1] < b["test"][0], f"splits overlap or are out of order: {b}"
    return b


def assign_split(ts: pd.Series, bounds: dict[str, tuple[int, int]]) -> pd.Series:
    """Split name for each timestamp; a timestamp between two splits (no transaction there)
    is assigned to the later split, since day-based boundaries lie at midnight."""
    out = pd.Series(pd.NA, index=ts.index, dtype="object")
    out[ts <= bounds["train"][1]] = "train"
    out[(ts > bounds["train"][1]) & (ts <= bounds["val"][1])] = "val"
    out[ts > bounds["val"][1]] = "test"
    assert not out.isna().any()
    return out


def ring_table(gt: pd.DataFrame, splits: dict[str, pd.DataFrame], bank_of: pd.Series) -> pd.DataFrame:
    """One row per ring_id in gt."""
    g = gt.groupby("ring_id", sort=True)
    pattern = g["pattern_type"].agg(lambda s: s.iloc[0])
    assert (g["pattern_type"].nunique() == 1).all(), "a ring has more than one pattern_type"
    n_lines = g.size().rename("n_pattern_lines")
    start = g["timestamp_int"].min().rename("start")
    end = g["timestamp_int"].max().rename("end")

    members = (pd.concat([gt[["ring_id", "from_id"]].rename(columns={"from_id": "acc"}),
                         gt[["ring_id", "to_id"]].rename(columns={"to_id": "acc"})])
               .drop_duplicates())
    members["bank"] = bank_of.reindex(members["acc"].values).values
    assert not members["bank"].isna().any(), "ring member without a bank_code"
    mg = members.groupby("ring_id")
    n_members = mg["acc"].nunique().rename("n_members")
    n_banks = mg["bank"].nunique().rename("n_banks")
    member_lists = mg["acc"].agg(lambda s: sorted(int(x) for x in s)).rename("members")

    # scope is defined on the ring's pattern lines, each assigned to a split by timestamp
    bounds = split_bounds(splits)
    line_split = assign_split(gt["timestamp_int"], bounds)
    counts = (pd.crosstab(gt["ring_id"], line_split).reindex(index=pattern.index, columns=SPLITS)
              .fillna(0).astype("int64").rename(columns={s: f"n_txn_{s}" for s in SPLITS}))
    counts["n_txn"] = counts[[f"n_txn_{s}" for s in SPLITS]].sum(axis=1)
    assert (counts["n_txn"] == n_lines).all()

    # rows of the transaction table labelled with the ring (>= lines because of duplicate payments)
    rows = {}
    for s, df in splits.items():
        rows[f"n_rows_{s}"] = df[df["ring_id"] != -1].groupby("ring_id").size()
    rows = pd.DataFrame(rows).reindex(pattern.index).fillna(0).astype("int64")
    rows["n_rows"] = rows[[f"n_rows_{s}" for s in SPLITS]].sum(axis=1)

    # visible membership: accounts on the ring's pattern lines inside each split
    vis_cols = []
    for sp in ("test", "val"):
        g_sp = gt[line_split == sp]
        mem_sp = (pd.concat([g_sp[["ring_id", "from_id"]].rename(columns={"from_id": "acc"}),
                             g_sp[["ring_id", "to_id"]].rename(columns={"to_id": "acc"})])
                  .drop_duplicates().groupby("ring_id")["acc"])
        vis_cols.append(mem_sp.nunique().reindex(pattern.index).fillna(0).astype("int64")
                        .rename(f"n_visible_members_{sp}"))
        vis_cols.append(mem_sp.agg(lambda x: sorted(int(v) for v in x)).reindex(pattern.index)
                        .rename(f"visible_members_{sp}"))
    vis_cols = pd.concat(vis_cols, axis=1)
    for sp in ("test", "val"):
        vis_cols[f"visible_members_{sp}"] = vis_cols[f"visible_members_{sp}"].apply(
            lambda v: v if isinstance(v, list) else [])

    t = pd.concat([pattern.rename("pattern_type"), n_lines, counts, rows, start, end, n_members, n_banks,
                   member_lists, vis_cols], axis=1)
    t["frac_test"] = np.where(t["n_txn"] > 0, t["n_txn_test"] / t["n_txn"].replace(0, np.nan), np.nan)
    t["frac_val"] = np.where(t["n_txn"] > 0, t["n_txn_val"] / t["n_txn"].replace(0, np.nan), np.nan)
    t["splits_present"] = [[s for s in SPLITS if r[f"n_txn_{s}"] > 0] for _, r in t.iterrows()]
    t["straddles"] = t["splits_present"].map(len) > 1
    for s in ("test", "val"):
        t[f"test_visible_{s}"] = t[f"n_txn_{s}"] > 0
        t[f"strict_{s}"] = (t[f"n_txn_{s}"] == t["n_txn"]) & (t["n_txn"] > 0)
        t[f"majority_{s}"] = t[f"n_txn_{s}"] / t["n_txn"].replace(0, np.nan) > 0.5
        t[f"majority_{s}"] = t[f"majority_{s}"].fillna(False).astype(bool)
    t["cross_bank"] = t["n_banks"] > 1
    t.index.name = "ring_id"
    return t.reset_index()


def _pattern_counts(df: pd.DataFrame) -> dict:
    return {k: int(v) for k, v in df["pattern_type"].value_counts().sort_index().items()}


def members_col(policy: str, split: str) -> str:
    """Which membership a policy scores: visible-in-split for test_visible, full otherwise."""
    return f"n_visible_members_{split}" if policy == "test_visible" else "n_members"


def scope_summary(t: pd.DataFrame) -> dict:
    lt3_all = t[t["n_members"] < 3]
    out = {"n_rings": int(len(t)),
           "n_rings_with_no_matched_rows": int((t["n_rows"] == 0).sum()),
           "n_pattern_lines": int(t["n_txn"].sum()),
           "n_matched_rows": int(t["n_rows"].sum()),
           "n_rings_straddling_any_boundary": int(t["straddles"].sum()),
           "n_rings_lt3_members": int(len(lt3_all)),
           "n_rings_lt3_members_by_pattern": _pattern_counts(lt3_all),
           "n_rings_cross_bank": int(t["cross_bank"].sum()),
           "cross_bank_fraction": float(t["cross_bank"].mean()) if len(t) else float("nan"),
           "n_rings_by_pattern": _pattern_counts(t)}
    for sp in ("test", "val"):
        touching = t[t[f"n_txn_{sp}"] > 0]
        block = {"n_rings_touching_split": int(len(touching)),
                 "n_rings_straddling": int(touching["straddles"].sum()),
                 "policies": {}}
        for pol in POLICIES:
            sel = t[t[f"{pol}_{sp}"]]
            mcol = members_col(pol, sp)
            lt3 = sel[sel[mcol] < 3]
            block["policies"][pol] = {
                "n_rings": int(len(sel)),
                "members_scored": "visible in split" if pol == "test_visible" else "full membership",
                "n_rings_lt3_members": int(len(lt3)),
                "n_rings_lt3_members_by_pattern": _pattern_counts(lt3),
                "n_rings_by_pattern": _pattern_counts(sel),
                "n_txn_in_scope_rings_in_split": int(sel[f"n_txn_{sp}"].sum()),
                "n_rows_in_scope_rings_in_split": int(sel[f"n_rows_{sp}"].sum()),
                "n_scored_members_total": int(sel[mcol].sum()),
            }
        out[sp] = block
    return out


# --------------------------------------------------------------------------- #
# ceiling
# --------------------------------------------------------------------------- #
def ceiling(t: pd.DataFrame, test: pd.DataFrame) -> dict:
    ring_rows = test[test["ring_id"] != -1]
    illicit = test[test["Is Laundering"] == 1]
    n_illicit = int(len(illicit))

    # per-account incident test-period transactions and how many of them are illicit
    inc = pd.concat([test[["from_id", "Is Laundering"]].rename(columns={"from_id": "acc"}),
                     test[["to_id", "Is Laundering"]].rename(columns={"to_id": "acc"})])
    per_acc = inc.groupby("acc")["Is Laundering"].agg(n_test_txn="size", n_illicit="sum")

    def block(policy: str) -> dict:
        sel = t[t[f"{policy}_test"]]
        ids = set(sel["ring_id"].tolist())
        n_in = int(illicit["ring_id"].isin(ids).sum())
        members = sorted({int(a) for m in sel["members"] for a in m})  # full membership
        st = per_acc.reindex(members)
        no_test = st["n_test_txn"].isna()
        all_licit = (~no_test) & (st["n_illicit"] == 0)
        n = len(members)
        return {
            "n_rings": int(len(sel)),
            "b_n_test_laundering_txn_in_scope_ring": n_in,
            "b_fraction": float(n_in / n_illicit) if n_illicit else float("nan"),
            "c_n_members_full": n,
            "c_n_members_no_test_txn": int(no_test.sum()),
            "c_fraction_no_test_txn": float(no_test.sum() / n) if n else float("nan"),
            "c_n_members_all_test_txn_licit": int(all_licit.sum()),
            "c_n_members_unrecoverable": int((no_test | all_licit).sum()),
            "c_fraction_unrecoverable": float((no_test | all_licit).sum() / n) if n else float("nan"),
        }

    return {
        "a_n_test_laundering_txn": n_illicit,
        "b_n_test_laundering_txn_in_any_ring": int((illicit["ring_id"] != -1).sum()),
        "primary_policy": "test_visible",
        "by_policy": {pol: block(pol) for pol in POLICIES},
        "note_ring_labelled_test_rows": int(len(ring_rows)),
        "note_ring_labelled_test_rows_with_licit_label": int((ring_rows["Is Laundering"] == 0).sum()),
        "c_definition": ("(c) counts in-scope-ring members by FULL membership that have no test-period "
                         "transaction at all, i.e. cannot be recovered from test evidence; "
                         "'unrecoverable' additionally counts members whose every test transaction is "
                         "labelled licit"),
    }


# --------------------------------------------------------------------------- #
def run(gt_path: Path, splits_dir: Path, out_path: Path, *, account_bank: Path | None = None,
        seed: int = 1, dry_run: bool = False, argv: list[str] | None = None) -> dict:
    gt = pd.read_parquet(gt_path)
    bank_of = bank_of_series(load_account_bank_map(account_bank))
    splits = load_split_labels(splits_dir)

    n_rings_total = int(gt["ring_id"].nunique())
    if dry_run:
        ids = pd.Series(sorted(gt["ring_id"].unique()))
        keep = ids.sample(n=max(1, round(DRY_RUN_FRAC * len(ids))), random_state=seed)
        gt = gt[gt["ring_id"].isin(keep)]
        splits = {s: df[df["ring_id"].isin(keep) | (df["ring_id"] == -1)] for s, df in splits.items()}

    t = ring_table(gt, splits, bank_of)
    summary = scope_summary(t)
    ceil = ceiling(t, splits["test"])

    per_ring = t.drop(columns=["members", "visible_members_test", "visible_members_val"]).copy()
    per_ring["start"] = per_ring["start"].astype(int)
    per_ring["end"] = per_ring["end"].astype(int)
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "command": "python preprocessing/ring_scope.py " + " ".join(argv or []),
        "inputs": {"gt": str(gt_path), "splits_dir": str(splits_dir),
                   "account_bank": str(account_bank or load_paths()["account_bank_map"])},
        "dry_run": dry_run, "dry_run_frac": DRY_RUN_FRAC if dry_run else None,
        "n_rings_total_in_gt": n_rings_total,
        "policy": POLICY,
        "summary": summary,
        "ceiling": ceil,
        "per_ring": json.loads(per_ring.to_json(orient="records")),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    s = summary
    print(f"[ring_scope] {s['n_rings']} rings -> {out_path}")
    for sp in ("test", "val"):
        parts = [f"{pol} {s[sp]['policies'][pol]['n_rings']} (<3: {s[sp]['policies'][pol]['n_rings_lt3_members']})"
                 for pol in POLICIES]
        print(f"  {sp}: " + ", ".join(parts) + f"; straddling {s[sp]['n_rings_straddling']}")
    print(f"  cross-bank rings: {s['n_rings_cross_bank']}/{s['n_rings']} = {s['cross_bank_fraction']:.3f}; "
          f"<3 members overall: {s['n_rings_lt3_members']} {s['n_rings_lt3_members_by_pattern']}")
    tv = ceil["by_policy"]["test_visible"]
    print(f"  ceiling (test_visible): (a) {ceil['a_n_test_laundering_txn']} test laundering txns; "
          f"(b) {tv['b_n_test_laundering_txn_in_scope_ring']} in in-scope rings; "
          f"(c) {tv['c_n_members_no_test_txn']}/{tv['c_n_members_full']} = {tv['c_fraction_no_test_txn']:.3f} "
          f"members with no test txn")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", type=Path, default=paths["processed_dir"] / "amlworld_ring_ground_truth.parquet")
    ap.add_argument("--splits", type=Path, default=paths["processed_dir"])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "ring_scope.json")
    ap.add_argument("--account-bank", type=Path, default=paths["account_bank_map"])
    ap.add_argument("--seed", type=int, default=None, help="dry-run ring sampling seed; default configs/seeds.yaml[0]")
    ap.add_argument("--dry-run", action="store_true", help=f"{DRY_RUN_FRAC:.0%} of rings, writes *_dryrun.json")
    args = ap.parse_args(argv)
    if args.seed is None:
        import yaml
        with open(REPO_ROOT / "configs" / "seeds.yaml") as f:
            args.seed = int(yaml.safe_load(f)["seeds"][0])
    out = args.out.with_name(args.out.stem + "_dryrun" + args.out.suffix) if args.dry_run else args.out
    run(args.gt, args.splits, out, account_bank=args.account_bank, seed=args.seed, dry_run=args.dry_run, argv=argv)


if __name__ == "__main__":
    main()
