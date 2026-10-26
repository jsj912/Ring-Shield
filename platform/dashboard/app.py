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
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
sys.path.insert(0, str(REPO_ROOT))
from contract.schema import TOPOLOGY_TYPES  # noqa: E402
from regeneration_flow import deadline_expired, new_poll_deadline  # noqa: E402
import client  # noqa: E402
from formatters import (fmt_amount, fmt_as_received, fmt_bool, fmt_closure, fmt_interval, fmt_recall,  # noqa: E402
                        fmt_percent, fmt_seconds, fmt_time, fmt_time_utc, fmt_weight)
import ring_graph  # noqa: E402

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


def _set_ring_page(page: int) -> None:
    st.session_state["ring_page"] = page


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

    chosen = {
        "status": statuses or ["open"], "topology_type": topology,
        "q": search.strip() or None,
        "min_conf": minimum, "cross_bank_only": cross_bank,
        "sort": sort, "order": order,
        "start_after": (datetime.combine(start_range[0], time.min, timezone.utc).isoformat()
                        if len(start_range) >= 1 else None),
        "start_before": (datetime.combine(start_range[-1], time.max, timezone.utc).isoformat()
                         if len(start_range) == 2 else None),
    }
    # Reset paging only when the filters really changed, so a repeated submit keeps the page.
    if ((apply_filters and chosen != st.session_state.get("ring_filter_values"))
            or "ring_filter_values" not in st.session_state):
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
    zone = st.context.timezone
    table = st.dataframe(
        [{"Ring ID": row["ring_id"],
          "Type": f"{row['topology_type']} (p = {fmt_as_received(row['topology_prob'])})",
          "Members": row["n_members"], "Edges": row["n_edges"],
          "Total": fmt_amount(row["total_amount"], row["total_currency"], row.get("total_partial")),
          "Window": f"{fmt_time(row['start_time'], zone)} → {fmt_time(row['end_time'], zone)}, "
                    f"{row['window_text']}",
          "Window (UTC)": f"{fmt_time_utc(row['start_time'])} → {fmt_time_utc(row['end_time'])}",
          "Confidence": fmt_weight(row["confidence"]), "Cross-bank": fmt_bool(row["cross_bank"]),
          "Status": row["status"]} for row in rows],
        use_container_width=True, hide_index=True, key=f"ring_table_{tenant_id}",
        on_select="rerun", selection_mode="single-row",
        column_config={"Total": st.column_config.TextColumn(
            help="From the ring's explanation, in its hub currency; '(partial)' means some "
                 "transactions had no exchange rate. Never converted here.")},
    )
    picked = table.selection.rows if table is not None and hasattr(table, "selection") else []
    if picked:                                         # FR-D14: clicking a row opens ring detail
        st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": rows[picked[0]]["ring_id"]}
        st.query_params["ring"] = rows[picked[0]]["ring_id"]
        st.session_state.pop(f"ring_table_{tenant_id}", None)   # do not reopen it on return
        st.rerun()
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
        # Callbacks change the page before the next run, with no mid-run st.rerun().
        st.button("Previous page", disabled=page == 0, key="ring_page_previous",
                  on_click=_set_ring_page, args=(max(0, page - 1),))
    with nav_right:
        st.button("Next page", disabled=not result.get("next_cursor"), key="ring_page_next",
                  on_click=_set_ring_page, args=(page + 1,))

    selected_ring = st.selectbox("Open ring", [row["ring_id"] for row in rows],
                                 key=f"select_ring_{tenant_id}")
    if st.button("View ring"):
        st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": selected_ring}
        st.rerun()


DETECTOR_CAPTION = "Signals from the transaction-level detector on the ring's seed transactions"


def _narrative_panel(ring: dict, explanation: dict | None, history: dict | None) -> None:
    """FR-D20-21: the narrative exactly as received, then the ring summary and latest verdict."""
    st.subheader("Narrative")
    if explanation is None:
        st.info("No verified explanation has been loaded for this ring yet.")
    else:
        st.text(explanation["narrative"])                          # byte for byte, never markdown
    zone = st.context.timezone
    rows = [
        ("Type", f"{ring['topology_type']} (p = {fmt_as_received(ring['topology_prob'])})"),
        ("Members", str(ring["n_members"])),
        ("Edges", str(ring["n_edges"])),
        ("Total amount", fmt_amount(ring["total_amount"], ring["total_currency"], ring.get("total_partial"))),
        ("Window", f"{fmt_time(ring['start_time'], zone)} → {fmt_time(ring['end_time'], zone)}, {ring['window_text']}"),
        ("Window (UTC)", f"{fmt_time_utc(ring['start_time'])} → {fmt_time_utc(ring['end_time'])}"),
        ("Conservation closure", fmt_closure(ring["conservation_closure"])),
        ("Cross-bank banks", ", ".join(ring["counterparty_banks"]) or "None"),
    ]
    st.table({"": [label for label, _ in rows], "Value": [value for _, value in rows]})
    st.caption(f"Model {ring['model_id']} · aggregator {ring['aggregator_id']}")
    latest = (history or {}).get("items") or []
    if latest:
        verdict = latest[0]
        tag = " · Simulated" if verdict["is_simulated"] else ""
        st.caption(f"Latest verdict: {verdict['verdict']} by {verdict['user_name']} at "
                   f"{fmt_time(verdict['created_at'], zone)}{tag}")


def _graph_panel(tenant_id: int, ring_id: str) -> None:
    """FR-D30-34, D36. A failure here stays in this panel (NFR-D32)."""
    st.subheader("Graph")
    show_conversions = st.toggle("Show currency conversions", value=False,
                                 key=f"graph_conversions_{tenant_id}_{ring_id}")
    subgraph = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/subgraph")
    if subgraph is None:
        st.caption("The graph could not be loaded; the narrative and evidence are unaffected.")
        return
    load_key = f"graph_load_all_{tenant_id}_{ring_id}"
    load_all = bool(st.session_state.get(load_key))
    try:
        if subgraph["n_accounts"] > ring_graph.NODE_CAP and not load_all:
            st.info(f"Showing {ring_graph.NODE_CAP} of {subgraph['n_accounts']} accounts")
            if st.button("Load all accounts", key=f"graph_load_all_button_{tenant_id}_{ring_id}"):
                st.session_state[load_key] = True
                st.rerun()
        figure = ring_graph.build_figure(subgraph, show_conversions=show_conversions, load_all=load_all)
        st.plotly_chart(figure, use_container_width=True, key=f"graph_{tenant_id}_{ring_id}")
    except Exception:                                              # noqa: BLE001 - keep other panels alive
        st.error("The graph could not be drawn for this ring; the narrative and evidence are unaffected.")


def _evidence_panel(tenant_id: int, ring_id: str, ring: dict, explanation: dict | None) -> None:
    """FR-D40-42: transactions, accounts and detector signals. Independent of the graph route."""
    st.subheader("Evidence")
    transactions_tab, accounts_tab, signals_tab = st.tabs(["Transactions", "Accounts", "Detector signals"])
    evidence = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/evidence", params={"limit": "500"})
    edges = {edge["edge_id"]: edge for edge in (evidence or {}).get("edges", [])}
    banks = {node["account_id"]: node["bank_label"] for node in (evidence or {}).get("nodes", [])}
    weights = {item["edge_id"]: item for item in (explanation or {}).get("edge_weights", [])}
    seeds = set(ring["seed_edges"])
    zone = st.context.timezone
    with transactions_tab:
        show_conversions = st.toggle("Show currency conversions", value=False,
                                     key=f"evidence_conversions_{tenant_id}_{ring_id}")
        rows = []
        for edge_id, edge in edges.items():
            if edge.get("is_conversion") and not show_conversions:
                continue
            weight = weights.get(edge_id, {})
            rows.append({
                "From": edge["source_account"], "To": edge["target_account"],
                "Amount": fmt_amount(edge["amount_sent"], edge["currency_sent"]),
                "Time": fmt_time(edge["timestamp"], zone),
                "Payment format": edge["payment_format"] or "—",
                "Kind": "conversion" if edge.get("is_conversion") else ("seed" if edge_id in seeds else "expanded"),
                "w_total": weight.get("w_total"), "w_score": fmt_weight(weight.get("w_score")),
                "w_loo": fmt_weight(weight.get("w_loo")), "w_flow": fmt_weight(weight.get("w_flow")),
            })
        rows.sort(key=lambda row: (row["w_total"] is not None, row["w_total"] or 0), reverse=True)
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True, column_config={
                "w_total": st.column_config.ProgressColumn("w_total", min_value=0.0, max_value=1.0, format="%.2f")})
        else:
            st.caption("No transactions are loaded for this ring.")
    with accounts_tab:
        accounts = sorted((explanation or {}).get("account_weights", []),
                          key=lambda item: (item.get("w_account") is not None, item.get("w_account") or 0),
                          reverse=True)
        if accounts:
            st.dataframe([{
                "Account": item["account_id"], "Bank": banks.get(item["account_id"]) or "—",
                "Role": item.get("role") or "—", "Inflow": fmt_amount(item.get("inflow")),
                "Outflow": fmt_amount(item.get("outflow")),
                "Hold time": fmt_seconds(item.get("hold_time_s")),
                "w_account": fmt_weight(item.get("w_account")),
            } for item in accounts], hide_index=True, use_container_width=True)
        else:
            st.caption("No account weights: the explanation has not been loaded.")
    with signals_tab:
        features = sorted((explanation or {}).get("feature_weights", []),
                          key=lambda item: abs(item.get("mean_shap") or 0), reverse=True)[:10]
        if features:
            labels = [item.get("display_name") or item["feature_name"] for item in features][::-1]
            values = [item["mean_shap"] for item in features][::-1]
            chart = go.Figure(go.Bar(
                x=values, y=labels, orientation="h",
                marker_color=["#c0392b" if value >= 0 else "#2471a3" for value in values],
                hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
            chart.update_layout(height=360, margin={"l": 10, "r": 10, "t": 10, "b": 10},
                                xaxis_title="mean SHAP (red raises suspicion, blue lowers it)")
            st.plotly_chart(chart, use_container_width=True, key=f"signals_{tenant_id}_{ring_id}")
        st.caption(DETECTOR_CAPTION)
    if explanation is not None:
        regenerated = " · Regenerated" if explanation.get("regenerated") else ""
        st.caption(f"Explainer {explanation['explainer_version']} · {explanation['latency_ms']} ms"
                   f" · revision {explanation['revision']}{regenerated}")


def _ring_detail(tenant_id: int, ring_id: str) -> None:
    if st.button("← Back to queue"):
        st.session_state.pop("open_ring", None)
        st.query_params.pop("ring", None)       # the queue keeps its filters and page (FR-D14)
        st.rerun()
    ring = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}")
    if ring is None:
        return
    explanation = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/explanation", quiet_not_found=True)
    history = _api("GET", f"/tenants/{tenant_id}/rings/{ring_id}/verdicts", params={"limit": "25"})
    st.header(f"Ring {ring['ring_id']}")
    st.markdown(f"**Status:** `{ring['status']}`")                 # status badge with its text
    _show_regeneration_state(tenant_id, ring_id, explanation)
    narrative_col, graph_col, evidence_col = st.columns([1.0, 1.4, 1.3], gap="medium")
    with narrative_col:
        _narrative_panel(ring, explanation, history)
    with graph_col:
        _graph_panel(tenant_id, ring_id)
    with evidence_col:
        _evidence_panel(tenant_id, ring_id, ring, explanation)
    _ring_verdicts(tenant_id, ring_id, history)
    _verdict_form(tenant_id, ring_id, ring)


def _verdict_label(item: dict) -> str:
    """FR-D54: a simulated verdict carries a 'Simulated' tag wherever it is shown."""
    return f"{item['verdict']} · Simulated" if item["is_simulated"] else item["verdict"]


def _ring_verdicts(tenant_id: int, ring_id: str, history: dict | None) -> None:
    st.subheader("Verdicts on this ring")
    if history is None:
        return
    if not history["items"]:
        st.caption("No verdicts have been recorded for this ring.")
        return
    zone = st.context.timezone
    st.dataframe(                                                  # notes are cells of text (NFR-D13)
        [{"When": fmt_time(item["created_at"], zone), "Investigator": item["user_name"],
          "Verdict": _verdict_label(item), "Note": item["note"] or ""} for item in history["items"]],
        use_container_width=True, hide_index=True, key=f"ring_verdicts_{tenant_id}_{ring_id}")
    if history.get("next_before_id"):
        st.caption("Older verdicts are listed on the Verdict history page.")


def _verdict_form(tenant_id: int, ring_id: str, ring: dict) -> None:
    """FR-D50-55: confirm, reject or partially correct; one request per click (FR-D53)."""
    st.subheader("Record a verdict")
    role = st.session_state["role"]
    if role not in {"analyst", "supervisor"}:
        st.warning("Administrators cannot record verdicts." if role == "admin"
                   else "Read-only: your role cannot record verdicts.")
        st.text_input("Note", disabled=True, key=f"note_disabled_{tenant_id}_{ring_id}")
        left, right, partial = st.columns(3)
        left.button("Confirm ring", disabled=True, key=f"detail_confirm_{tenant_id}_{ring_id}")
        right.button("Reject ring", disabled=True, key=f"detail_reject_{tenant_id}_{ring_id}")
        partial.button("Partially correct", disabled=True, key=f"detail_partial_{tenant_id}_{ring_id}")
        return
    if ring["status"] != "open":
        st.info("This ring is no longer open for verdicts.")
        return
    submitted_key = f"verdict_submitted_{tenant_id}_{ring_id}"
    disabled = bool(st.session_state.get("verdict_in_flight")) or st.session_state.get(submitted_key, False)
    failed_key = f"verdict_failed_{tenant_id}_{ring_id}"
    partial_key = f"partial_form_open_{tenant_id}_{ring_id}"
    if st.session_state.get(partial_key):
        st.markdown("**Partially correct:** untick the accounts and transactions that are not part of the ring.")
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
            if not corrected_members:
                st.error("Keep at least one account for a partial correction.")
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
                    st.session_state.pop(failed_key, None)
                    st.success("Verdict recorded")
                    st.rerun()
                st.session_state[failed_key] = True
    else:
        note = st.text_input(
            "Note (optional for confirm or reject)", key=f"note_{tenant_id}_{ring_id}"
        )
        left, right, partial = st.columns(3)
        for column, label, kind, primary in ((left, "Confirm ring", "confirm", True),
                                             (right, "Reject ring", "reject", False)):
            if column.button(label, type="primary" if primary else "secondary", disabled=disabled,
                             key=f"detail_{kind}_{tenant_id}_{ring_id}"):
                if _record_verdict(tenant_id, ring_id, kind, note or None):
                    st.session_state.pop(failed_key, None)
                    st.success("Verdict recorded")
                    st.rerun()
                st.session_state[failed_key] = True
        if partial.button("Partially correct", key=f"detail_partial_{tenant_id}_{ring_id}",
                          disabled=disabled):
            st.session_state[partial_key] = True
            st.rerun()
    if st.session_state.get(failed_key):
        st.caption("The verdict was not recorded. Your entries are kept: submit again to retry.")


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


RETRAIN_SCOPE = ("Retrains the expansion and affinity models; the typing model is fixed. "
                 "The result is promoted only if it passes the holdout gate.")


def _model_versions(tenant_id: int) -> None:
    """FR-D70-73: model versions with the gate's reason, and (supervisors) retraining runs."""
    st.header("Models")
    result = _api("GET", f"/tenants/{tenant_id}/models", params={"limit": "100"})
    if result is None:
        return
    st.caption(f"Active model {result['active_model_id']} · seed {result['active_seed']}")
    if st.session_state["role"] == "supervisor":
        _retrain_section(tenant_id)
    st.subheader("Model versions")
    if not result["items"]:
        st.info("No model versions are registered for this tenant.")
        return
    focus = st.session_state.get(f"model_focus_{tenant_id}")
    zone = st.context.timezone
    rows = [{"Version ID": item["model_version_id"], "Component": item["component"],
             "Version": item["version_tag"], "Trained at": fmt_time(item["trained_at"], zone),
             "Training labels": item["train_label_count"],
             "Holdout ring-F1": fmt_as_received(item["holdout_ring_f1"]),
             "Promoted": fmt_bool(item["promoted"]),
             "Gate reason": item["gate_reason"] or "",
             "Shared": fmt_bool(item["shared"])} for item in result["items"]]

    def highlight(row):                                # the promoted version per component (FR-D70)
        if row["Version ID"] == focus:
            colour = "background-color: rgba(255, 196, 0, 0.30)"
        elif row["Promoted"] == "Yes":
            colour = "background-color: rgba(46, 160, 67, 0.22)"
        else:
            colour = ""
        return [colour for _ in row]

    st.dataframe(pd.DataFrame(rows).style.apply(highlight, axis=1), use_container_width=True,
                 hide_index=True, key=f"model_table_{tenant_id}")
    st.caption("Green rows are the versions currently promoted for each component; newest first.")
    if result.get("next_before_id") is not None:
        st.caption("More versions are available through the API cursor.")


def _confirm_retrain(tenant_id: int) -> None:
    """The confirmation step before a retrain (FR-D71), inline so it cannot be dismissed half-open."""
    box = st.container(border=True)
    box.markdown("**Retrain now?**")
    box.write(RETRAIN_SCOPE)
    left, right = box.columns(2)
    if left.button("Start retraining", type="primary", key=f"retrain_confirm_{tenant_id}"):
        st.session_state.pop(f"retrain_dialog_{tenant_id}", None)
        queued = _api("POST", f"/tenants/{tenant_id}/retrain")
        if queued:
            st.session_state[f"retrain_run_{tenant_id}"] = queued["run_id"]
            st.rerun()
    if right.button("Cancel", key=f"retrain_cancel_{tenant_id}"):
        st.session_state.pop(f"retrain_dialog_{tenant_id}", None)
        st.rerun()


def _retrain_section(tenant_id: int) -> None:
    st.subheader("Retraining")
    if st.button("Retrain now", key=f"retrain_{tenant_id}"):
        st.session_state[f"retrain_dialog_{tenant_id}"] = True
    if st.session_state.get(f"retrain_dialog_{tenant_id}"):   # open until started or cancelled
        _confirm_retrain(tenant_id)
    run_id = st.session_state.get(f"retrain_run_{tenant_id}")
    if run_id:
        _retrain_status(tenant_id, run_id)
    runs = _api("GET", f"/tenants/{tenant_id}/retrain", params={"limit": "50"})
    if runs is None:
        return
    if not runs["items"]:
        st.info("No retraining runs yet.")
        return
    zone = st.context.timezone
    st.dataframe(
        [{"Run ID": row["run_id"], "Status": row["status"],
          "Started": fmt_time(row["started_at"], zone), "Finished": fmt_time(row["finished_at"], zone),
          "Promoted version": row["model_version_id"] if row["model_version_id"] is not None else "—",
          "Candidates": ", ".join(f"{c['component']} #{c['model_version_id']}" for c in row["candidates"])}
         for row in runs["items"]],
        use_container_width=True, hide_index=True, key=f"retrain_runs_{tenant_id}")
    for row in runs["items"]:
        _refusals(tenant_id, row["run_id"], row["candidates"])


def _refusals(tenant_id: int, run_id: str, candidates: list[dict]) -> None:
    """FR-D73: a refused candidate's gate reason, prominently, with a link to its version row."""
    for candidate in candidates:
        if candidate["promoted"]:
            continue
        st.error(f"Run {run_id}: {candidate['component']} refused by the holdout gate: "
                 f"{candidate['gate_reason']}")
        version_id = candidate["model_version_id"]
        if st.button(f"Show model version {version_id}", key=f"focus_{tenant_id}_{run_id}_{version_id}"):
            st.session_state[f"model_focus_{tenant_id}"] = version_id
            st.rerun()


@st.fragment(run_every="5s")
def _retrain_status(tenant_id: int, run_id: str) -> None:
    """FR-D72: poll the run every 5 s until it finishes; the log tail sits in an expander."""
    status = _api("GET", f"/tenants/{tenant_id}/retrain/{run_id}")
    if status is None:
        return
    finished = status["status"] in {"succeeded", "failed"}
    st.markdown(f"**Run {run_id}:** `{status['status']}`")
    with st.expander("Log tail", expanded=not finished):
        if status["log_lines"]:
            st.code("\n".join(status["log_lines"]), language="text")
        else:
            st.caption("No retraining log output yet.")
    if finished and st.session_state.pop(f"retrain_run_{tenant_id}", None):
        st.rerun()                                     # stop polling; the runs list shows the result


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
        stored_range = tuple(datetime.fromisoformat(filters[key]).date()
                             for key in ("since", "until") if filters.get(key))
        date_range = st.date_input("Verdict date range", value=stored_range)
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
    zone = st.context.timezone
    table = st.dataframe(                                          # newest first, as the API sorts
        [{"When": fmt_time(item["created_at"], zone), "Ring ID": item["ring_id"],
          "Verdict": _verdict_label(item), "Analyst": item["analyst_label"],
          "Note": item["note_excerpt"] or ""} for item in rows],
        use_container_width=True, hide_index=True, key=f"verdict_table_{tenant_id}_{page}",
        on_select="rerun", selection_mode="single-row",
        column_config={"Ring ID": st.column_config.TextColumn(help="Click a row to open the ring")},
    )
    picked = table.selection.rows if table is not None and hasattr(table, "selection") else []
    if picked:                                         # FR-D60: the ring id opens the ring
        ring_id = rows[picked[0]]["ring_id"]
        st.session_state["open_ring"] = {"tenant_id": tenant_id, "ring_id": ring_id}
        st.session_state["navigate_to_ring_detail"] = True
        st.session_state.pop(f"verdict_table_{tenant_id}_{page}", None)
        st.query_params["page"] = "rings"
        st.query_params["ring"] = ring_id
        st.rerun()
    if rows:
        st.caption("Click a row to open its ring.")

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


R10_DEGENERATE = {70: "degenerate: no ring edges visible"}


def _r10_interval(part: dict) -> str:
    return fmt_interval(part["value"], part["low"], part["high"])


def _r10_per_tenant(results: dict) -> dict:
    """(row, tenant) -> per-tenant record, a lookup into what the API sent."""
    return {(item["row"], item["tenant_id"]): item for item in results["per_tenant"]}


def _r10_primary_table(results: dict) -> list[dict]:
    """Change 6: one row per tenant with pooled, (a), (b) and budget-matched; the CI is on the
    pooled-across-tenants row and the per-tenant rows are descriptive."""
    rows, lookup = results["rows"], _r10_per_tenant(results)
    table = []
    for tenant in rows["primary"]["tenants"]:
        b = lookup.get(("primary", tenant), {})
        table.append({
            "Tenant": str(tenant), "Kind": "per tenant (descriptive)", "Rings": str(b.get("n_rings", "—")),
            "Pooled": fmt_recall(b.get("pooled_recall")),
            "(a) pooled scores, own edges": fmt_recall(lookup.get(("pooled_scores", tenant), {}).get("tenant_recall")),
            "(b) own scores, own edges": fmt_recall(b.get("tenant_recall")),
            "Budget-matched": fmt_recall(lookup.get(("budget_matched", tenant), {}).get("tenant_recall")),
            "Pooled − (b)": "—",
        })
    table.append({
        "Tenant": "All five", "Kind": "pooled across tenants (95% CI)",
        "Rings": f"{rows['primary']['n_rings']} rings, {rows['primary']['n_pairs']} pairs",
        "Pooled": _r10_interval(rows["primary"]["pooled"]),
        "(a) pooled scores, own edges": _r10_interval(rows["pooled_scores"]["tenant"]),
        "(b) own scores, own edges": _r10_interval(rows["primary"]["tenant"]),
        "Budget-matched": _r10_interval(rows["budget_matched"]["tenant"]),
        "Pooled − (b)": _r10_interval(rows["primary"]["difference"]),
    })
    return table


def _r10_robustness_table(results: dict) -> list[dict]:
    row, lookup = results["rows"]["robustness"], _r10_per_tenant(results)
    table = []
    for tenant in row["tenants"]:
        item = lookup.get(("robustness", tenant))
        table.append({
            "Tenant": str(tenant), "Kind": "per tenant (descriptive)",
            "Rings": str(item["n_rings"]) if item else "—",
            "Pooled": fmt_recall(item["pooled_recall"]) if item else "—",
            "(b) own scores, own edges": fmt_recall(item["tenant_recall"]) if item else "—",
            "Note": R10_DEGENERATE.get(tenant, ""),
        })
    table.append({
        "Tenant": "All five", "Kind": "pooled across tenants (95% CI)",
        "Rings": f"{row['n_rings']} rings, {row['n_pairs']} pairs",
        "Pooled": _r10_interval(row["pooled"]), "(b) own scores, own edges": _r10_interval(row["tenant"]),
        "Note": "degenerate set: bank 70 has no visible ring laundering edge",
    })
    return table


def _render_admin_r10_results(results: dict) -> None:
    """FR-D91-92 with change 6, from the registered R10 result."""
    st.markdown(f"**Cross-bank rings:** {results['cross_bank_rings']} of {results['n_in_scope_rings']} "
                f"({fmt_percent(results['cross_bank_fraction'])}) · **mean banks per ring** "
                f"{fmt_as_received(results['mean_banks_per_ring'])}")
    st.caption(f"Days {', '.join(str(d) for d in results['window_days'])}, {results['scope']}, "
               f"Jaccard {results['jaccard']}, seeds {', '.join(str(s) for s in results['seeds'])}, "
               f"bootstrap over rings ({results['n_boot']:,} resamples). Computed {results['created_utc']}.")
    st.subheader("Primary set (banks 1, 20, 11, 118, 12)")
    st.dataframe(_r10_primary_table(results), use_container_width=True, hide_index=True,
                 key="admin_r10_primary")
    st.caption("(a): the pooled model's scores, restricted to the bank's own edges. (b): the bank's "
               "own model on its own edges. Budget-matched: (b) with the pooled seed count. "
               "Ring recall only; member coverage was not part of R10 as registered.")
    st.subheader("Robustness set (banks 70, 12, 11, 1, 10)")
    st.dataframe(_r10_robustness_table(results), use_container_width=True, hide_index=True,
                 key="admin_r10_robustness")
    lookup = _r10_per_tenant(results)
    tenants = results["rows"]["primary"]["tenants"]
    figure = go.Figure()
    for field, label in (("tenant_recall", "(b) own scores, own edges"), ("pooled_recall", "Pooled")):
        figure.add_trace(go.Bar(x=[str(t) for t in tenants],
                                y=[lookup[("primary", t)][field] for t in tenants], name=label))
    figure.update_layout(barmode="group", height=320, xaxis_title="Bank (primary set)",
                         yaxis_title="Ring recall", margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(figure, use_container_width=True, key="admin_r10_chart")
    st.caption("Per-bank bars are descriptive; the claim is the pooled-across-tenants row.")


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
    if status == "succeeded" and state.get("results"):
        _render_admin_r10_results(state["results"])
        if state.get("message"):
            st.caption(state["message"])


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
    job = st.session_state.get("admin_r10_job")
    _poll_admin_r10()
    if not (isinstance(job, dict) and job.get("status") == "succeeded"):
        latest = _api("GET", "/admin/experiments/tenant-vs-pooled/latest", quiet_not_found=True)
        if latest is None:
            st.info("No R10 result has been computed yet. Press Run to compute it.")
        else:
            st.subheader("Latest registered result")
            _render_admin_r10_results(latest["results"])


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
