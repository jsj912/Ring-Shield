"""Thin Streamlit client for the RingShield API."""

from __future__ import annotations

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

API_BASE = os.environ.get("RINGSHIELD_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _api(method: str, path: str, *, body: dict | None = None, params=None,
         quiet_not_found: bool = False):
    api_calls = st.session_state.setdefault("_api_retry_keys", [])
    call_number = len(api_calls)
    api_calls.append((method, path))
    retry_key = f"retry_{method}_{path}_{call_number}"
    headers = {}
    if st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state['token']}"
    try:
        with st.spinner("Loading..."):
            response = httpx.request(method, f"{API_BASE}{path}", headers=headers,
                                     json=body, params=params, timeout=20.0)
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


def _active_tenant() -> tuple[int | None, str | None]:
    if st.session_state["role"] != "admin":
        return st.session_state["tenant_id"], st.session_state["tenant_name"]
    tenants = _api("GET", "/admin/tenants")
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
    with st.sidebar.form("ring_filters"):
        statuses = st.multiselect("Status", ["open", "confirmed", "rejected", "partial"],
                                  default=["open"])
        topology = st.multiselect("Topology", TOPOLOGY_TYPES)
        minimum = st.slider("Minimum confidence", min_value=0.0, max_value=1.0,
                            value=0.0, step=0.01)
        cross_bank = st.checkbox("Cross-bank only")
        sort = st.selectbox("Sort by", ["confidence", "total_amount", "start_time", "members"])
        order = st.selectbox("Order", ["desc", "asc"])
        start_range = st.date_input("Start date range", value=())
        apply_filters = st.form_submit_button("Apply filters")

    if apply_filters or "ring_filter_values" not in st.session_state:
        st.session_state["ring_filter_values"] = {
            "status": statuses or ["open"], "topology_type": topology,
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
    for key in ("min_conf", "cross_bank_only", "sort", "order", "start_after", "start_before"):
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
    if explanation is None:
        st.info("No verified L4 explanation has been loaded for this ring yet.")
    else:
        st.write(explanation["narrative"])
        st.caption(f"Explainer {explanation['explainer_version']} · {explanation['latency_ms']} ms")
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

    if st.session_state["role"] == "admin":
        st.warning("Administrators cannot record verdicts.")
        return
    st.subheader("Record a verdict")
    note = st.text_input("Note (optional for confirm or reject)", key=f"note_{tenant_id}_{ring_id}")
    left, right = st.columns(2)
    if left.button("Confirm ring", type="primary"):
        result = _api("POST", f"/tenants/{tenant_id}/rings/{ring_id}/verdicts",
                      body={"verdict": "confirm", "note": note})
        if result:
            st.success("Verdict recorded")
            st.rerun()
    if right.button("Reject ring"):
        result = _api("POST", f"/tenants/{tenant_id}/rings/{ring_id}/verdicts",
                      body={"verdict": "reject", "note": note})
        if result:
            st.success("Verdict recorded")
            st.rerun()
    st.button("Partially correct", disabled=True,
              help="Partial correction requires the L4 regeneration interface.")


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


def _clear_session_state() -> None:
    for key in list(st.session_state.keys()):
        if not key.startswith("$$"):
            del st.session_state[key]


def main() -> None:
    st.set_page_config(page_title="RingShield Investigator", layout="wide")
    st.session_state["_api_retry_keys"] = []
    if not st.session_state.get("token"):
        _login()
        return
    st.sidebar.title(st.session_state.get("tenant_name", "RingShield"))
    st.sidebar.caption(f"Role: {st.session_state['role']}")
    st.sidebar.caption(f"Time origin: {os.environ.get('RINGSHIELD_TIME_ORIGIN_UTC', 'not configured')}")
    if st.sidebar.button("Sign out"):
        _clear_session_state()
        _login()
        return
    tenant_id, tenant_name = _active_tenant()
    if tenant_id is None:
        return
    st.sidebar.caption(f"Viewing: {tenant_name}")
    page = st.sidebar.radio("Workspace", ["Investigations", "Model registry", "Score drift"])
    if page == "Model registry":
        _model_versions(tenant_id)
    elif page == "Score drift":
        _drift_events(tenant_id)
    else:
        open_ring = st.session_state.get("open_ring")
        if isinstance(open_ring, dict) and open_ring.get("tenant_id") == tenant_id:
            _ring_detail(tenant_id, open_ring["ring_id"])
        else:
            st.session_state.pop("open_ring", None)
            _queue(tenant_id)


if __name__ == "__main__":
    main()
