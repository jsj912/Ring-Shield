"""No-op stand-in for `wandb`, so MEGA-GNN's `training.py` can be imported without it.

`third_party/mega_gnn/training.py` imports wandb at module level and logs to it from its own
training loops. `models/mega_adapter.py` imports that module only for `get_model` -- it runs its
own loop and writes our artefacts -- so nothing here is ever called during a Ring-Shield run.
Every entry point therefore either does nothing or raises loudly rather than silently pretending
a run was logged. This module is only importable via `third_party/shims`, which is put on
sys.path by the adapter; it does not shadow a real wandb install anywhere else.
"""
from __future__ import annotations


class _Unused:
    def __getattr__(self, name):
        raise RuntimeError(
            f"wandb.{name} was called, but third_party/shims/wandb.py is a stub: MEGA-GNN's own "
            "training loops are not used by models/mega_adapter.py. Install wandb if you mean to "
            "run third_party/mega_gnn/main.py.")


config = _Unused()
run = None


def log(*args, **kwargs):  # their loops call this per batch; never reached from the adapter
    raise RuntimeError("wandb.log called: see third_party/shims/wandb.py")


def init(*args, **kwargs):
    raise RuntimeError("wandb.init called: see third_party/shims/wandb.py")


def finish(*args, **kwargs):
    return None
