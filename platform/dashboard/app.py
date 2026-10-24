"""Thin Streamlit client for the RingShield API."""

from __future__ import annotations

import csv
import io
import itertools
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path

import httpx
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
sys.path.insert(0, str(REPO_ROOT))
from contract.schema import TOPOLOGY_TYPES  # noqa: E402
from regeneration_flow import deadline_expired, new_poll_deadline  # noqa: E402
import client  # noqa: E402

API_BASE = client.API_BASE
_API_CALL_COUNTER = itertools.count()


def _csv_safe_text(value):
    """Prefix spreadsheet formula markers in text cells; preserve other values."""
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return f"'{value}"
    return value


def _api(method: str, path: str, *, body: dict | None = None, params=None,
         quiet_not_found: bool = False):
    call_number = next(_API_CALL_COUNTER)
    retry_key = f"retry_{call_number}_{method}_{path}"
    try:
        with st.spinner("Loading..."):
            response = client.send(method, path, token=st.session_state.get("token"),
                                   body=body, params=params)
    except httpx.HTTPError as exc:
        st.error(f"RingShield API is unavailable: {exc}")
        if st.button("Retry", key=retry_key):
            st.rerun()
        return None
    if response.status_code == 401:
        if method.upper() == "POST" and path == "/auth/login":
            st.error("Incorrect email or password.")
            return None
        for key in ("token", "user", "tenant_id", "tenant_name", "role", "selected_tenant"):
            st.session_state.pop(key, None)
        st.session_state["notice"] = "Session expired. Please sign in again."
        st.rerun()
    if response.status_code == 403:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        suffix = f" (request id {request_id})" if request_id else ""
        st.warning(f"Not permitted: your role cannot do this.{suffix}")
        return None
    if not response.is_success:
        if response.status_code == 404 and quiet_not_found:
            return None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = payload.get("message", "Request failed") if isinstance(payload, dict) else "Request failed"
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        request_id = request_id or response.headers.get("X-Request-ID")
        suffix = f" (request id {request_id})" if request_id else ""
        st.error(f"{message}{suffix}")
        if st.button("Retry", key=retry_key):
            st.rerun()
        return None
    if response.status_code == 204:
        return {}
    return response.json()


def _login() -> None:
    notice = st.session_state.pop("notice", None)
    if notice:
        st.info(notice)
    st.title("RingShield Investigator")
    st.caption("Sign in to view your bank's ring queue.")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        session = _api("POST", "/auth/login", body={"email": email, "password": password})
        if session:
            st.session_state["token"] = session["token"]
            st.session_state["user"] = session["user_id"]
            st.session_state["tenant_id"] = session["tenant_id"]
            st.session_state["tenant_name"] = session["tenant_name"]
            st.session_state["role"] = session["role"]
            st.session_state.pop("selected_tenant", None)
            st.rerun()


def _active_tenant(tenant_records=None) -> tuple[int | None, str | None]:
    if st.session_state["role"] != "admin":
        return st.session_state["tenant_id"], st.session_state["tenant_name"]
    tenants = tenant_records if tenant_records is not None else _api("GET", "/admin/tenants")
    if tenants is None:
        return None, None
    loaded = [item for item in tenants if item["is_loaded"]]
    if not loaded:
        st.info("No tenant is marked as loaded yet.")
        return None, None
    labels = {f"{item['name']} ({item['bank_code']})": item for item in loaded}
    default = st.session_state.get("selected_tenant")
    keys = list(labels)
    default_index = next((i for i, label in enumerate(keys)
                          if labels[label]["tenant_id"] == default), 0)
    selected = st.sidebar.selectbox("Tenant", keys, index=default_index)
    item = labels[selected]
    st.session_state["selected_tenant"] = item["tenant_id"]
    return item["tenant_id"], item["name"]


def _queue(tenant_id: int) -> None:
    st.header("Ring queue")
    # The widgets start from the stored filters, so returning from a ring shows what is applied.
    stored = st.session_state.get("ring_filter_values", {})
    sort_options, order_options = ["confidence", "total_amount", "start_time", "members"], ["desc", "asc"]
    with st.sidebar.form("ring_filters"):
        statuses = st.multiselect("Status", ["open", "confirmed", "rejected", "partial"],
                                  default=stored.get("status", ["open"]))
        topology = st.multiselect("Topology", TOPOLOGY_TYPES, default=stored.get("topology_type", []))
        search = st.text_input("Search ring ID or account ID", value=stored.get("q") or "")
        minimum = st.slider("Minimum confidence", min_value=0.0, max_value=1.0,
                            value=float(stored.get("min_conf", 0.0)), step=0.01)
        cross_bank = st.checkbox("Cross-bank only", value=bool(stored.get("cross_bank_only", False)))
        sort = st.selectbox("Sort by", sort_options,
                            index=sort_options.index(stored.get("sort", "confidence")))
        order = st.selectbox("Order", order_options, index=order_options.index(stored.get("order", "desc")))
        start_range = st.date_input("Start date range", value=())
        apply_filters = st.form_submit_button("Apply filters")

    if apply_filters or "ring_filter_values" not in st.session_state:
        st.session_state["ring_filter_values"] = {
            "status": statuses or ["open"], "topology_type": topology,
            "q": search.strip() or None,
            "min_conf": minimum, "cross_bank_only": cross_bank,
            "sort": sort, "order": order,
            "start_after": (datetime.combine(start_range[0], time.min, timezone.utc).isoformat()
                            if len(start_range) >= 1 else None),
            "start_before": (datetime.combine(start_range[-1], time.max, timezone.utc).isoformat()
                             if len(start_range) == 2 else None),
        }
        st.session_state["ring_cursors"] = [None]
        st.session_state["ring_page"] = 0

    filters = st.session_state.get("ring_filter_values", {"status": ["open"]})
    params = [("status", value) for value in filters.get("status", ["open"])]
    params.extend(("topology_type", value) for value in filters.get("topology_type", []))
    for key in ("min_conf", "cross_bank_only", "sort", "order", "start_after", "start_before", "q"):
        value = filters.get(key)
        if value is not None:
            params.append((key, str(value).lower() if isinstance(value, bool) else str(value)))
    cursors = st.session_state.setdefault("ring_cursors", [None])
    page = st.session_state.setdefault("ring_page", 0)
    if page > 0 and len(cursors) > page:
        params.append(("cursor", cursors[page]))
    params.append(("limit", "50"))
    result = _api("GET", f"/tenants/{tenant_id}/rings", params=params)
    if result is None:
        return
    st.caption(f"{result['total']} rings match these filters")
    rows = result.get("items", [])
    if not rows:
        if result.get("tenant_total", 0) == 0:
            st.info("No rings have been generated for this tenant yet")
        else:
            st.info("No rings match these filters")
        return
    st.dataframe(
        [{"Ring ID": row["ring_id"], "Type": f"{row['topology_type']} ({row['topology_prob']:.0%})",
          "Members": row["n_members"], "Edges": row["n_edges"],
          "Total": (f"{row['total_amount']:,.2f} {row['total_currency']}"
                    if row["total_amount"] is not None else "—"),
          "Window": f"{row['start_time']} → {row['end_time']} ({row['window_text']})",
          "Confidence": row["confidence"], "Cross-bank": row["cross_bank"],
          "Status": row["status"]} for row in rows],
        use_container_width=True, hide_index=True,
    )
    role = st.session_state["role"]
    if role == "admin":
        st.warning("Administrators cannot record verdicts.")
    for row in rows:
        if row["status"] != "open":
            continue
        action_left, action_mid, action_right = st.columns([4, 1, 1])
        action_left.write(f"Ring {row['ring_id']}")
        submitted_key = f"verdict_submitted_{tenant_id}_{row['ring_id']}"
        in_flight = bool(st.session_state.get("verdict_in_flight"))
        if role not in {"analyst", "supervisor"}:
            action_mid.button("Confirm", key=f"queue_confirm_{tenant_id}_{row['ring_id']}", disabled=True)
            action_right.button("Reject", key=f"queue_reject_{tenant_id}_{row['ring_id']}", disabled=True)
            continue
        if action_mid.button("Confirm", key=f"queue_confirm_{tenant_id}_{row['ring_id']}",
                             disabled=in_flight or st.session_state.get(submitted_key, False)):
            st.session_state["pending_quick_verdict"] = {
                "tenant_id": tenant_id, "ring_id": row["ring_id"], "verdict": "confirm",
            }
            st.rerun()
        if action_right.button("Reject", key=f"queue_reject_{tenant_id}_{row['ring_id']}",
                               disabled=in_flight or st.session_state.get(submitted_key, False)):
            st.session_state["pending_quick_verdict"] = {
                "tenant_id": tenant_id, "ring_id": row["ring_id"], "verdict": "reject",
            }
            st.rerun()
        pending = st.session_state.get("pending_quick_verdict")
        if pending == {"tenant_id": tenant_id, "ring_id": row["ring_id"], "verdict": "confirm"}:
            st.warning(f"Confirm ring {row['ring_id']}?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm verdict", key=f"queue_confirm_verdict_{tenant_id}_{row['ring_id']}",
                                  disabled=in_flight):
                if _record_verdict(tenant_id, row["ring_id"], "confirm"):
                    st.success("Verdict recorded")
                    st.rerun()
            if cancel_col.button("Cancel confirmation", key=f"queue_cancel_verdict_{tenant_id}_{row['ring_id']}"):
                st.session_state.pop("pending_quick_verdict", None)
                st.rerun()
        elif pending == {"tenant_id": tenant_id, "ring_id": row["ring_id"], "verdict": "reject"}:
            st.warning(f"Reject ring {row['ring_id']}?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Reject verdict", key=f"queue_reject_verdict_{tenant_id}_{row['ring_id']}",
                                  disabled=in_flight):
                if _record_verdict(tenant_id, row["ring_id"], "reject"):
                    st.success("Verdict recorded")
                    st.rerun()
            if cancel_col.button("Cancel confirmation", key=f"queue_cancel_reject_{tenant_id}_{row['ring_id']}"):
                st.session_state.pop("pending_quick_verdict", None)
                st.rerun()
    if result.get("next_cursor"):
        if len(cursors) <= page + 1:
            cursors.append(result["next_cursor"])
    nav_left, nav_right = st.columns(2)
    with nav_left:
        if st.button("Previous page", disabled=page == 0):
            st.session_state["ring_page"] = max(0, page - 1)
            st.rerun()
    with nav_right:
        if st.button("Next page", disabled=not result.get("next_cursor")):
            st.session_state["ring_page"] = page + 1
            st.rerun()

    selected_ring = st.selectbox("Open ring", [row["ring_id"] for row in rows],
                                 key=f"select_ring_{tenant_id}")
    if st.button("View ring"):
        st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": selected_ring}
        st.rerun()


def _ring_detail(tenant_id: int, ring_id: str) -> None:
    if st.button("← Back to queue"):
        st.session_state.pop("open_ring", None)
        st.rerun()
    ring = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}")
    if ring is None:
        return
    st.header(f"Ring {ring['ring_id']}")
    st.caption(f"{ring['topology_type']} · {ring['n_members']} members · {ring['n_edges']} edges · {ring['window_text']} · {ring['status']}")
    st.write({key: ring[key] for key in (
        "total_amount", "total_currency", "n_currencies", "start_time", "end_time",
        "confidence", "cross_bank", "counterparty_banks", "conservation_closure",
        "model_id", "aggregator_id",
    )})
    st.subheader("Accounts")
    st.write(ring["member_accounts"])
    st.subheader("Transactions")
    st.write(ring["member_edges"])
    evidence = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/evidence",
                    params={"limit": "250"})
    if evidence is not None:
        if evidence["missing_edge_ids"]:
            st.warning(f"Evidence is incomplete: {len(evidence['missing_edge_ids'])} ring edges are not loaded.")
        if not evidence["edges"]:
            st.caption("No transaction evidence is loaded for this ring.")
        else:
            account_nodes = {item["account_id"]: item for item in evidence["nodes"]}
            dot_ids = {account_id: f"acct_{'n' if account_id < 0 else 'p'}{abs(account_id)}"
                       for account_id in account_nodes}
            dot = ["digraph ring {", "rankdir=LR;", "node [style=filled, fillcolor=\"#e8eef7\"];"]
            for account_id, node in account_nodes.items():
                flags = [label for label, field in (("source", "is_source"),
                                                    ("sink", "is_sink"),
                                                    ("mule", "is_mule")) if node[field]]
                role_suffix = f" ({', '.join(flags)})" if flags else ""
                label = f"Account {account_id}{role_suffix}\\n{node['bank_label'] or 'Bank unknown'}"
                color = "#f2b6b6" if node["is_mule"] else "#e8eef7"
                dot.append(f'{dot_ids[account_id]} [label="{label}", fillcolor="{color}"];')
            for edge in evidence["edges"]:
                dot.append(f'{dot_ids[edge["source_account"]]} -> {dot_ids[edge["target_account"]]} '
                           f'[label="edge {edge["edge_id"]}"];')
            dot.append("}")
            st.graphviz_chart("\n".join(dot), use_container_width=True)
            if evidence.get("next_before_edge_id") is not None:
                st.caption("Graph shows the first 250 transactions. More evidence is available through the API cursor.")
            st.dataframe(
                [{"Edge": edge["edge_id"], "From account": edge["source_account"],
                  "To account": edge["target_account"], "Time (UTC)": edge["timestamp"],
                  "Amount sent": edge["amount_sent"], "Sent currency": edge["currency_sent"],
                  "Amount received": edge["amount_received"],
                  "Received currency": edge["currency_received"],
                  "Payment format": edge["payment_format"],
                  "Calibrated score": edge["calibrated_score"], "Seed": edge["is_seed"]}
                 for edge in evidence["edges"]],
                use_container_width=True, hide_index=True,
            )
    explanation = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/explanation",
                       quiet_not_found=True)
    st.subheader("L4 explanation")
    _show_regeneration_state(tenant_id, ring_id, explanation)
    if explanation is None:
        st.info("No verified L4 explanation has been loaded for this ring yet.")
    else:
        st.write(explanation["narrative"])
        regenerated_label = " · Regenerated" if explanation.get("regenerated") else ""
        st.caption(
            f"Explainer {explanation['explainer_version']} · {explanation['latency_ms']} ms"
            f" · revision {explanation['revision']}{regenerated_label}"
        )
        with st.expander("Evidence summary"):
            st.json(explanation["evidence_summary"])
        if explanation["edge_weights"]:
            st.markdown("**Edge contribution weights**")
            st.dataframe(explanation["edge_weights"], use_container_width=True, hide_index=True)
        if explanation["account_weights"]:
            st.markdown("**Account contribution weights**")
            st.dataframe(explanation["account_weights"], use_container_width=True, hide_index=True)
        if explanation["feature_weights"]:
            st.markdown("**Feature contributions**")
            st.dataframe(explanation["feature_weights"], use_container_width=True, hide_index=True)
        with st.expander("Explanation provenance"):
            st.json(explanation["provenance"])

    st.subheader("Verdict history")
    history = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/verdicts",
                   params={"limit": "25"})
    if history is not None:
        if not history["items"]:
            st.caption("No verdicts have been recorded for this ring.")
        else:
            st.dataframe(
                [{"When (UTC)": item["created_at"], "Investigator": item["user_name"],
                  "Verdict": item["verdict"], "Note": item["note"] or "",
                  "Simulated": item["is_simulated"]} for item in history["items"]],
                use_container_width=True, hide_index=True,
            )
            if history.get("next_before_id"):
                st.caption("More history is available through the API using next_before_id.")

    if st.session_state["role"] not in {"analyst", "supervisor"}:
        if st.session_state["role"] == "admin":
            st.warning("Administrators cannot record verdicts.")
        else:
            st.warning("Read-only: your role cannot record verdicts.")
        return
    st.subheader("Record a verdict")
    if ring["status"] != "open":
        st.info("This ring is no longer open for verdicts.")
        return
    submitted_key = f"verdict_submitted_{tenant_id}_{ring_id}"
    disabled = bool(st.session_state.get("verdict_in_flight")) or st.session_state.get(submitted_key, False)
    partial_key = f"partial_form_open_{tenant_id}_{ring_id}"
    if st.session_state.get(partial_key):
        st.subheader("Partially correct")
        with st.form(f"partial_correction_{tenant_id}_{ring_id}"):
            keep_members = {
                account_id: st.checkbox(
                    f"Keep account {account_id}", value=True,
                    key=f"partial_keep_account_{tenant_id}_{ring_id}_{account_id}",
                )
                for account_id in ring["member_accounts"]
            }
            keep_edges = {
                edge_id: st.checkbox(
                    f"Keep transaction {edge_id}", value=True,
                    key=f"partial_keep_transaction_{tenant_id}_{ring_id}_{edge_id}",
                )
                for edge_id in ring["member_edges"]
            }
            partial_note = st.text_area(
                "Note (required for partial)", key=f"partial_note_{tenant_id}_{ring_id}"
            )
            submit_partial = st.form_submit_button(
                "Submit partial verdict", disabled=disabled,
            )
        cancel_left, _ = st.columns(2)
        if cancel_left.button("Cancel partial correction", key=f"cancel_partial_{tenant_id}_{ring_id}"):
            st.session_state.pop(partial_key, None)
            st.rerun()
        if submit_partial:
            corrected_members = [account for account, keep in keep_members.items() if keep]
            corrected_edges = [edge for edge, keep in keep_edges.items() if keep]
            if not corrected_members[1:]:
                st.error("Keep at least two accounts for a partial correction.")
            elif all(keep_members.values()) and all(keep_edges.values()):
                st.error("Remove at least one account or transaction; otherwise confirm the ring.")
            elif not partial_note.strip():
                st.error("A note is required for a partial verdict.")
            else:
                result = _record_verdict(
                    tenant_id, ring_id, "partial", partial_note,
                    corrected_members=corrected_members, corrected_edges=corrected_edges,
                )
                if result:
                    st.session_state.pop(partial_key, None)
                    st.success("Verdict recorded")
                    st.rerun()
    else:
        note = st.text_input(
            "Note (optional for confirm or reject)", key=f"note_{tenant_id}_{ring_id}"
        )
        left, right, partial = st.columns(3)
        if left.button("Confirm ring", type="primary", key=f"detail_confirm_{tenant_id}_{ring_id}", disabled=disabled):
            result = _record_verdict(tenant_id, ring_id, "confirm", note)
            if result:
                st.success("Verdict recorded")
                st.rerun()
        if right.button("Reject ring", key=f"detail_reject_{tenant_id}_{ring_id}", disabled=disabled):
            result = _record_verdict(tenant_id, ring_id, "reject", note)
            if result:
                st.success("Verdict recorded")
                st.rerun()
        if partial.button("Partially correct", key=f"detail_partial_{tenant_id}_{ring_id}",
                         disabled=disabled):
            st.session_state[partial_key] = True
            st.rerun()


def _record_verdict(tenant_id: int, ring_id: str, verdict: str, note: str | None = None,
                    *, corrected_members: list[int] | None = None,
                    corrected_edges: list[int] | None = None):
    submitted_key = f"verdict_submitted_{tenant_id}_{ring_id}"
    if st.session_state.get("verdict_in_flight") or st.session_state.get(submitted_key):
        return None
    st.session_state["verdict_in_flight"] = True
    try:
        body = {"verdict": verdict, "note": note}
        if verdict == "partial":
            body["corrected_members"] = corrected_members or []
            body["corrected_edges"] = corrected_edges or []
        result = _api("POST", f"/tenants/{tenant_id}/rings/{ring_id}/verdicts", body=body)
        if result:
            st.session_state[submitted_key] = True
            st.session_state.pop("pending_quick_verdict", None)
            if verdict == "partial":
                regeneration = result.get("regeneration")
                if (isinstance(regeneration, dict)
                        and regeneration.get("status") == "queued"
                        and regeneration.get("job_id")):
                    st.session_state["ring_regeneration"] = {
                        "tenant_id": tenant_id, "ring_id": ring_id,
                        "verdict_id": result["verdict_id"],
                        "job_id": regeneration["job_id"], "status": "queued",
                        "deadline": new_poll_deadline(), "error": None,
                    }
                else:
                    st.session_state["ring_regeneration"] = {
                        "tenant_id": tenant_id, "ring_id": ring_id,
                        "verdict_id": result["verdict_id"],
                        "job_id": None,
                        "status": "unavailable", "error": None,
                    }
        return result
    finally:
        st.session_state["verdict_in_flight"] = False


def _retry_regeneration(tenant_id: int, ring_id: str, state: dict) -> None:
    result = _api(
        "POST", f"/tenants/{tenant_id}/rings/{ring_id}/explanation/regenerate",
        body={"verdict_id": state["verdict_id"]},
    )
    if result is not None:
        state.update({
            "job_id": result["job_id"], "status": result["status"],
            "error": result.get("error"), "deadline": new_poll_deadline(),
        })
        st.session_state["ring_regeneration"] = state
        st.rerun()


@st.fragment(run_every="2s")
def _poll_regeneration(tenant_id: int, ring_id: str) -> None:
    state = st.session_state.get("ring_regeneration")
    if (not isinstance(state, dict) or state.get("tenant_id") != tenant_id
            or state.get("ring_id") != ring_id
            or state.get("status") not in {"queued", "running"}):
        return
    if deadline_expired(state.get("deadline")):
        st.info("Still working, refresh later.")
        return
    status = _api(
        "GET",
        f"/tenants/{tenant_id}/rings/{ring_id}/explanation/jobs/{state['job_id']}",
    )
    if status is None:
        return
    state.update({
        "status": status["status"], "result_revision": status.get("result_revision"),
        "error": status.get("error"),
    })
    st.session_state["ring_regeneration"] = state
    if state["status"] == "succeeded":
        st.rerun()
    if state["status"] == "failed":
        st.error(state.get("error") or "Explanation regeneration failed")
        retry_key = f"retry_regeneration_{tenant_id}_{ring_id}_{state['job_id']}"
        if st.button("Retry", key=retry_key):
            _retry_regeneration(tenant_id, ring_id, state)
        return
    st.info("Regenerating explanation...")


def _show_regeneration_state(tenant_id: int, ring_id: str,
                             explanation: dict | None) -> None:
    state = st.session_state.get("ring_regeneration")
    if (isinstance(state, dict) and state.get("tenant_id") == tenant_id
            and state.get("ring_id") == ring_id):
        status = state.get("status")
        if status in {"queued", "running"}:
            _poll_regeneration(tenant_id, ring_id)
        elif status == "failed":
            st.error(state.get("error") or "Explanation regeneration failed")
            retry_key = f"retry_regeneration_{tenant_id}_{ring_id}_{state['job_id']}"
            if st.button("Retry", key=retry_key):
                _retry_regeneration(tenant_id, ring_id, state)
        elif status == "unavailable":
            st.info("The verdict was recorded, but the explanation could not be regenerated.")
        elif status == "timed_out":
            st.info("Still working, refresh later.")
    elif explanation is not None and explanation.get("regenerating"):
        st.info("Regenerating explanation...")


def _model_versions(tenant_id: int) -> None:
    st.header("Model registry")
    result = _api("GET", f"/tenants/{tenant_id}/models", params={"limit": "100"})
    if result is None:
        return
    if st.session_state["role"] == "supervisor":
        runs = _api("GET", f"/tenants/{tenant_id}/retrain", params={"limit": "50"})
        if runs is not None:
            if not runs["items"]:
                st.info("No retraining runs yet.")
            else:
                st.dataframe(
                    [{"Run ID": row["run_id"], "Status": row["status"],
                      "Started (UTC)": row["started_at"], "Finished (UTC)": row["finished_at"],
                      "Model version": row["model_version_id"]} for row in runs["items"]],
                    use_container_width=True, hide_index=True,
                )
        if st.button("Retrain now", key=f"retrain_{tenant_id}"):
            queued = _api("POST", f"/tenants/{tenant_id}/retrain")
            if queued:
                st.session_state[f"retrain_run_{tenant_id}"] = queued["run_id"]
        run_id = st.session_state.get(f"retrain_run_{tenant_id}")
        if run_id:
            status_result = _api("GET", f"/tenants/{tenant_id}/retrain/{run_id}")
            if status_result:
                st.write(f"Retrain run: {status_result['status']}")
                if status_result["log_lines"]:
                    st.code("\n".join(status_result["log_lines"]), language="text")
                else:
                    st.caption("No retraining log output yet.")
    if not result["items"]:
        st.info("No model versions are registered for this tenant.")
        return
    st.dataframe(
        [{"Component": item["component"], "Version": item["version_tag"],
          "Trained at (UTC)": item["trained_at"], "Training labels": item["train_label_count"],
          "Holdout ring F1": item["holdout_ring_f1"], "Promoted": item["promoted"],
          "Shared model": item["shared"]} for item in result["items"]],
        use_container_width=True, hide_index=True,
    )
    if result.get("next_before_id") is not None:
        st.caption("More versions are available through the API cursor.")
    st.caption("Artifact paths and model files are not exposed in the investigator dashboard.")


def _verdicts(tenant_id: int) -> None:
    st.header("Verdicts")
    filters = st.session_state.get("verdict_filter_values", {
        "verdict": [], "analyst_id": None, "simulated": None,
        "since": None, "until": None,
    })
    params = [("verdict", value) for value in filters["verdict"]]
    for key in ("analyst_id", "simulated", "since", "until"):
        value = filters.get(key)
        if value is not None:
            params.append((key, str(value).lower() if isinstance(value, bool) else str(value)))
    cursors = st.session_state.setdefault("verdict_cursors", [None])
    page = st.session_state.setdefault("verdict_page", 0)
    if page > 0 and len(cursors) > page:
        params.append(("cursor", cursors[page]))
    params.append(("limit", "50"))
    result = _api("GET", f"/tenants/{tenant_id}/verdicts", params=params)
    if result is None:
        return

    analyst_options = {f"Analyst {item['analyst_id']}": item["analyst_id"]
                       for item in result.get("analysts", [])}
    labels = ["All analysts", *analyst_options]
    default_analyst = next((label for label, value in analyst_options.items()
                            if value == filters.get("analyst_id")), "All analysts")
    with st.sidebar.form("verdict_filters"):
        verdicts = st.multiselect("Verdict type", ["confirm", "reject", "partial"],
                                  default=filters["verdict"])
        analyst_label = st.selectbox("Analyst", labels, index=labels.index(default_analyst))
        simulation = st.selectbox("Simulated or real", ["All", "Simulated", "Real"],
                                  index=(0 if filters.get("simulated") is None else
                                         1 if filters["simulated"] else 2))
        date_range = st.date_input("Verdict date range", value=())
        apply_filters = st.form_submit_button("Apply verdict filters")
    if apply_filters:
        st.session_state["verdict_filter_values"] = {
            "verdict": verdicts,
            "analyst_id": analyst_options.get(analyst_label),
            "simulated": (None if simulation == "All" else simulation == "Simulated"),
            "since": (datetime.combine(date_range[0], time.min, timezone.utc).isoformat()
                      if len(date_range) >= 1 else None),
            "until": (datetime.combine(date_range[-1], time.max, timezone.utc).isoformat()
                      if len(date_range) == 2 else None),
        }
        st.session_state["verdict_cursors"] = [None]
        st.session_state["verdict_page"] = 0
        st.rerun()

    counts = result["counts"]
    st.caption(f"{result['total']} verdicts match these filters")
    count_cols = st.columns(3)
    count_cols[0].metric("Confirmed", counts["confirmed"])
    count_cols[1].metric("Rejected", counts["rejected"])
    count_cols[2].metric("Partial", counts["partial"])
    rows = result.get("items", [])
    st.dataframe(
        [{"When (UTC)": item["created_at"], "Ring ID": item["ring_id"],
          "Verdict": item["verdict"], "Analyst": item["analyst_label"],
          "Simulated": "Simulated" if item["is_simulated"] else "Real",
          "Note": item["note_excerpt"] or ""} for item in rows],
        use_container_width=True, hide_index=True,
    )
    ring_ids = list(dict.fromkeys(item["ring_id"] for item in rows))
    if ring_ids:
        selected_ring = st.selectbox("Open ring from verdict history", ring_ids,
                                     key=f"verdict_ring_{tenant_id}_{page}")
        if st.button("Open ring", key=f"open_verdict_ring_{tenant_id}_{page}"):
            st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": selected_ring}
            st.session_state["navigate_to_ring_detail"] = True
            st.rerun()

    export_key = f"verdict_export_{tenant_id}"
    if st.button("Prepare CSV export", key=f"prepare_verdict_csv_{tenant_id}"):
        export_rows = []
        export_cursor = None
        seen_cursors = set()
        while True:
            export_params = [("verdict", value) for value in filters["verdict"]]
            for key in ("analyst_id", "simulated", "since", "until"):
                value = filters.get(key)
                if value is not None:
                    export_params.append((key, str(value).lower()
                                          if isinstance(value, bool) else str(value)))
            if export_cursor:
                export_params.append(("cursor", export_cursor))
            export_params.append(("limit", "100"))
            export_page = _api("GET", f"/tenants/{tenant_id}/verdicts", params=export_params)
            if export_page is None:
                break
            export_rows.extend(export_page["items"])
            export_cursor = export_page.get("next_cursor")
            if not export_cursor or export_cursor in seen_cursors:
                break
            seen_cursors.add(export_cursor)
        output = io.StringIO(newline="")
        fields = ("created_at", "ring_id", "verdict", "analyst_label",
                  "is_simulated", "note_excerpt")
        text_fields = {"ring_id", "verdict", "analyst_label", "note_excerpt"}
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows({
            field: (_csv_safe_text(item[field]) if field in text_fields else item[field])
            for field in fields
        } for item in export_rows)
        st.session_state[export_key] = output.getvalue()
    if st.session_state.get(export_key) is not None:
        st.download_button("Download CSV", st.session_state[export_key],
                            file_name="verdicts.csv", mime="text/csv",
                            key=f"download_verdict_csv_{tenant_id}")
    st.caption("CSV export includes all rows matching the active filters.")

    if result.get("next_cursor"):
        if len(cursors) <= page + 1:
            cursors.append(result["next_cursor"])
    nav_left, nav_right = st.columns(2)
    with nav_left:
        if st.button("Previous verdict page", disabled=page == 0,
                     key=f"verdict_previous_{tenant_id}"):
            st.session_state["verdict_page"] = max(0, page - 1)
            st.rerun()
    with nav_right:
        if st.button("Next verdict page", disabled=not result.get("next_cursor"),
                     key=f"verdict_next_{tenant_id}"):
            st.session_state["verdict_page"] = page + 1
            st.rerun()


def _drift_events(tenant_id: int) -> None:
    st.header("Score drift")
    if st.session_state["role"] != "supervisor":
        st.info("Drift review is available to tenant supervisors.")
        return
    series = _api("GET", f"/tenants/{tenant_id}/drift/series")
    monitor = st.selectbox("Monitor", ["All", "adwin_score_mean", "adwin_score_p99"])
    params = {"limit": "100"}
    if monitor != "All":
        params["monitor"] = monitor
    result = _api("GET", f"/tenants/{tenant_id}/drift", params=params)
    if result is None:
        return
    if series and series["items"]:
        figure = go.Figure()
        for field, label in (("mean", "Daily mean"), ("p99", "Daily 99th percentile")):
            figure.add_trace(go.Scatter(
                x=[item["day"] for item in series["items"]],
                y=[item[field] for item in series["items"]],
                mode="lines", name=label,
            ))
        for monitor_id, field, label in (
            ("adwin_score_mean", "statistic", "Mean drift detected"),
            ("adwin_score_p99", "statistic", "P99 drift detected"),
        ):
            detected = [item for item in result["items"] if item["monitor"] == monitor_id]
            if detected:
                figure.add_trace(go.Scatter(
                    x=[item["window_end"] for item in detected],
                    y=[item[field] for item in detected],
                    mode="markers", marker={"symbol": "diamond", "size": 11}, name=label,
                ))
        st.plotly_chart(figure, use_container_width=True)
    elif series:
        st.info("No daily score statistics are available for this tenant.")
    if not result["items"]:
        st.info("No drift events have been recorded for this tenant.")
        return
    for item in result["items"]:
        left, right = st.columns([5, 1])
        left.write(
            f"{item['detected_at']} · {item['monitor']} · "
            f"window {item['window_start']} to {item['window_end']} · "
            f"statistic {item['statistic']:.4f} · delta {item['threshold']}"
        )
        action = "Mark reviewed" if not item["acted_on"] else "Mark unreviewed"
        if right.button(action, key=f"drift_{tenant_id}_{item['event_id']}"):
            updated = _api(
                "PATCH", f"/tenants/{tenant_id}/drift/{item['event_id']}",
                body={"acted_on": not item["acted_on"]},
            )
            if updated:
                st.rerun()
    if result.get("next_before_id") is not None:
        st.caption("More drift events are available through the API cursor.")
    st.caption("Drift events are informational and do not trigger automatic retraining.")


def _start_admin_r10() -> None:
    started = _api("POST", "/admin/experiments/tenant-vs-pooled")
    if started:
        st.session_state["admin_r10_job"] = {
            **started, "deadline": new_poll_deadline(),
        }


def _render_admin_r10_results(status: dict) -> None:
    results = status.get("results") or {}
    table_rows = results.get("table_rows") or []
    if table_rows:
        display_rows = []
        columns = (
            ("tenant_id", "Tenant"), ("seed", "Seed"),
            ("tenant_ring_recall", "Tenant recall"),
            ("tenant_ring_recall_ci_low", "Tenant recall CI low"),
            ("tenant_ring_recall_ci_high", "Tenant recall CI high"),
            ("tenant_member_coverage", "Tenant member coverage"),
            ("pooled_ring_recall", "Pooled recall"),
            ("pooled_ring_recall_ci_low", "Pooled recall CI low"),
            ("pooled_ring_recall_ci_high", "Pooled recall CI high"),
            ("pooled_member_coverage", "Pooled member coverage"),
            ("tenant_truth_cross_bank_fraction", "Cross-bank fraction"),
            ("tenant_truth_mean_banks_per_ring", "Mean banks per ring"),
            ("cross_bank_truth_fraction", "Overall cross-bank fraction"),
            ("mean_banks_per_truth_ring", "Overall mean banks per ring"),
        )
        for row in table_rows:
            display_rows.append({label: row.get(key) for key, label in columns})
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("The status response does not include R10 metric rows.")

    recall_series = results.get("recall_series") or []
    if recall_series:
        figure = go.Figure()
        for field, label in (("tenant_ring_recall", "Tenant recall"),
                             ("pooled_ring_recall", "Pooled recall")):
            figure.add_trace(go.Bar(
                x=[f"{row['tenant_id']} · seed {row['seed']}" for row in recall_series],
                y=[row.get(field) for row in recall_series],
                name=label,
            ))
        st.plotly_chart(figure, use_container_width=True)
    if status.get("message"):
        st.caption(status["message"])
    if results.get("limitations"):
        st.caption(results["limitations"])
    st.caption("R10 displays aggregate evaluation metrics only; no ground-truth labels or ring IDs are shown.")


@st.fragment(run_every="2s")
def _poll_admin_r10() -> None:
    state = st.session_state.get("admin_r10_job")
    if not isinstance(state, dict):
        return
    status = state.get("status")
    st.subheader("Tenant vs pooled experiment")
    if status in {"queued", "running"}:
        if deadline_expired(state.get("deadline")):
            st.info("Still working, refresh later.")
            return
        latest = _api(
            "GET", f"/admin/experiments/tenant-vs-pooled/{state['job_id']}"
        )
        if latest is None:
            return
        state.update(latest)
        state["deadline"] = state.get("deadline") or new_poll_deadline()
        st.session_state["admin_r10_job"] = state
        status = state.get("status")
    st.caption(f"Status: {status}")
    if status == "failed":
        st.error(state.get("message") or "The R10 experiment failed.")
        if st.button("Retry", key="admin_r10_retry"):
            _start_admin_r10()
            st.rerun()
        return
    if status == "succeeded":
        _render_admin_r10_results(state)


def _admin_page(tenant_records: list[dict]) -> None:
    st.title("Admin")
    st.header("Tenants")
    st.dataframe([
        {
            "Tenant ID": tenant["tenant_id"],
            "Bank code": tenant["bank_code"],
            "Name": tenant["name"],
            "Loaded": "Yes" if tenant["is_loaded"] else "No",
            "Rings": tenant.get("ring_count", 0),
            "Verdicts": tenant.get("verdict_count", 0),
        }
        for tenant in tenant_records
    ], use_container_width=True, hide_index=True)

    st.header("Users")
    st.info("Tenant user listings are unavailable because the API has no user-list endpoint.")

    st.header("R10 tenant vs pooled")
    if st.button("Run", key="admin_r10_start"):
        _start_admin_r10()
        st.rerun()
    _poll_admin_r10()


# Page slugs (Section 3: /rings, /verdicts, /models, /drift, /admin) and their sidebar labels.
PAGE_LABELS = {"rings": "Ring queue", "verdicts": "Verdict history", "models": "Models",
               "drift": "Drift", "admin": "Admin"}
PAGE_ROLES = {"rings": {"analyst", "supervisor", "admin"},
              "verdicts": {"analyst", "supervisor", "admin"},
              "models": {"analyst", "supervisor", "admin"},     # analyst: read-only
              "drift": {"supervisor", "admin"},
              "admin": {"admin"}}


def pages_for(role: str) -> list[str]:
    return [slug for slug in PAGE_LABELS if role in PAGE_ROLES[slug]]


def _requested_page() -> str | None:
    """The page named in the URL (?page=drift), if any; unknown names are ignored."""
    value = st.query_params.get("page")
    return value if value in PAGE_LABELS else None


def _clear_session_state() -> None:
    for key in list(st.session_state.keys()):
        if not key.startswith("$$"):
            del st.session_state[key]


def main() -> None:
    global _API_CALL_COUNTER
    st.set_page_config(page_title="RingShield Investigator", layout="wide")
    _API_CALL_COUNTER = itertools.count()
    if st.session_state.pop("navigate_to_ring_detail", False):
        st.session_state["workspace_page"] = PAGE_LABELS["rings"]
    if not st.session_state.get("token"):
        _login()
        return
    st.sidebar.title(st.session_state.get("tenant_name", "RingShield"))
    st.sidebar.caption(f"Role: {st.session_state['role']}")
    st.sidebar.caption(f"Time origin: {os.environ.get('RINGSHIELD_TIME_ORIGIN_UTC', 'not configured')}")
    if client.fixture_dir() is not None:
        st.sidebar.caption("Fixture mode: no API")
    role = st.session_state["role"]
    requested = _requested_page()
    if requested is not None and requested not in pages_for(role):
        # reached by URL; never shown in navigation for this role (FR-D05)
        st.warning("Not permitted")
        return
    tenant_records = _api("GET", "/admin/tenants") if role == "admin" else None
    if role == "admin" and tenant_records is None:
        return
    tenant_id, tenant_name = _active_tenant(tenant_records)
    if tenant_name is not None:
        st.sidebar.caption(f"Viewing: {tenant_name}")
    labels = [PAGE_LABELS[slug] for slug in pages_for(role)]
    # A page typed into the URL is applied once; after that the sidebar drives the URL.
    if requested is not None and requested != st.session_state.get("_url_page"):
        st.session_state["workspace_page"] = PAGE_LABELS[requested]
    if st.session_state.get("workspace_page") not in labels:
        st.session_state.pop("workspace_page", None)
    label = st.sidebar.radio("Workspace", labels, key="workspace_page")
    page = next(slug for slug, text in PAGE_LABELS.items() if text == label)
    st.session_state["_url_page"] = page
    st.query_params["page"] = page
    # Sign out sits at the bottom of the sidebar (Section 3) and clears token, data and URL (FR-D04).
    if st.sidebar.button("Sign out"):
        _clear_session_state()
        st.query_params.clear()
        st.rerun()
    if page == "admin":
        _admin_page(tenant_records)
        return
    if tenant_id is None:
        return
    if role == "admin" and page in {"rings", "verdicts"}:
        st.info("Read-only (administrator)")
    if page == "models":
        _model_versions(tenant_id)
    elif page == "drift":
        _drift_events(tenant_id)
    elif page == "verdicts":
        _verdicts(tenant_id)
    else:
        ring_param = st.query_params.get("ring")
        if ring_param and not isinstance(st.session_state.get("open_ring"), dict):
            st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": ring_param}
        open_ring = st.session_state.get("open_ring")
        if isinstance(open_ring, dict) and open_ring.get("tenant_id") == tenant_id:
            _ring_detail(tenant_id, open_ring["ring_id"])
        else:
            st.session_state.pop("open_ring", None)
            _queue(tenant_id)


if __name__ == "__main__":
    main()
