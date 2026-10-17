"""Create the bank registry from a normalized account-to-bank mapping.

Input columns are `account_id` and `bank_code` (the preprocessing artifact
`account_bank.parquet` has this shape). Account numbers are never copied.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import bcrypt
import pandas as pd
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "platform"))

from db.models import Tenant, User  # noqa: E402
from db.session import db_session  # noqa: E402


def seed_tenants(account_map_path: Path, loaded_bank_codes: set[int]) -> dict[str, int]:
    if account_map_path.suffix.lower() == ".parquet":
        account_map = pd.read_parquet(account_map_path, columns=["account_id", "bank_code"])
    else:
        account_map = pd.read_csv(account_map_path, usecols=["account_id", "bank_code"])
    if account_map.empty:
        raise ValueError("account map contains no rows")
    if account_map[["account_id", "bank_code"]].isna().any().any():
        raise ValueError("account_id and bank_code must be non-null")
    account_map["account_id"] = account_map["account_id"].astype("int64")
    account_map["bank_code"] = account_map["bank_code"].astype("int64")
    if (account_map["bank_code"] < 0).any():
        raise ValueError("bank codes must be non-negative; -1 is reserved for pooled data")
    bank_codes = set(account_map["bank_code"].unique().tolist())
    unknown = sorted(loaded_bank_codes - bank_codes)
    if unknown:
        raise ValueError(f"selected bank codes are absent from the account map: {unknown[:10]}")

    rows = [{"tenant_id": code, "bank_code": code, "name": f"Bank {code}",
             "is_loaded": code in loaded_bank_codes} for code in sorted(bank_codes)]
    simulated_password_hash = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("ascii")
    simulated_users = [{
        "tenant_id": code,
        "email": f"simulated.analyst@tenant{code}.local",
        "password_hash": simulated_password_hash,
        "role": "analyst",
        "disabled": False,
    } for code in sorted(bank_codes)]
    with db_session(role="admin") as session:
        for offset in range(0, len(rows), 5_000):
            chunk = rows[offset:offset + 5_000]
            stmt = insert(Tenant).values(chunk)
            session.execute(stmt.on_conflict_do_update(
                index_elements=[Tenant.tenant_id],
                set_={"bank_code": stmt.excluded.bank_code,
                      "name": stmt.excluded.name,
                      "is_loaded": stmt.excluded.is_loaded},
            ))
        for offset in range(0, len(simulated_users), 5_000):
            stmt = insert(User).values(simulated_users[offset:offset + 5_000])
            session.execute(stmt.on_conflict_do_nothing(index_elements=[User.email]))
    return {"banks": len(bank_codes), "accounts": int(account_map["account_id"].nunique()),
            "loaded": len(loaded_bank_codes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-map", required=True, type=Path)
    parser.add_argument("--loaded-bank", type=int, action="append", default=[],
                        help="bank code to load as a tenant; repeat after the ring-member analysis")
    args = parser.parse_args(argv)
    try:
        print(seed_tenants(args.account_map, set(args.loaded_bank)))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
