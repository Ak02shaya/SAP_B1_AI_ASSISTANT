import streamlit as st
import requests
import os
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import holidays

load_dotenv()
MIDDLEWARE_BASE_URL = os.getenv("MIDDLEWARE_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="SAP B1 Copilot", layout="centered")

# --- Auth (Database Sign-In Gate) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0
if "username" not in st.session_state:
    st.session_state.username = None

if not st.session_state.authenticated:
    st.title("🔐 SAP B1 Endpoint Login")

    if st.session_state.login_attempts >= 3:
        st.error("Account locked due to 3 failed attempts. Please contact administrator.")
        st.stop()

    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")

        if st.form_submit_button("Sign In"):
            if not u.strip() or not p:
                st.warning("Please enter both username and password.")
            else:
                try:
                    auth_res = requests.post(
                        f"{MIDDLEWARE_BASE_URL}/api/v1/login",
                        json={"username": u.strip(), "password": p},
                        timeout=15,
                    )
                    if auth_res.status_code == 200:
                        st.session_state.authenticated = True
                        st.session_state.username = auth_res.json().get("username", u.strip())
                        st.session_state.login_attempts = 0
                        st.rerun()
                    elif auth_res.status_code == 401:
                        st.session_state.login_attempts += 1
                        if st.session_state.login_attempts >= 3:
                            st.error("Account locked due to 3 failed attempts. Please contact administrator.")
                        else:
                            st.error(f"Invalid username or password. Attempt {st.session_state.login_attempts} of 3.")
                    else:
                        detail = auth_res.json().get("detail", auth_res.text)
                        st.error(f"Login error ({auth_res.status_code}): {detail}")
                except requests.exceptions.RequestException as e:
                    st.error(f"Cannot reach authentication server: {e}")
    st.stop()


# --- Excel Helpers ---
EXPORT_KEYWORDS = r"\b(excel|xlsx|sheet|spreadsheet|export|download|report|generate|make|create|file)\b"
FOLLOWUP_FILLERS = r"\b(excel|xlsx|sheet|spreadsheet|export|download|report|generate|give|get|make|create|file|me|the|a|an|it|this|that|as|in|to|into|please|pls|for|of|above|previous|same|data|result|results)\b"


def wants_excel(prompt: str) -> bool:
    """Triggers Excel download if any export/generate keyword is present."""
    return bool(re.search(EXPORT_KEYWORDS, prompt, re.IGNORECASE))


def is_followup_export(prompt: str) -> bool:
    """True ONLY when the message is a pure export command with no new question words."""
    if not wants_excel(prompt):
        return False
    remaining = re.sub(FOLLOWUP_FILLERS, "", prompt.lower())
    remaining = re.sub(r"[^a-z0-9]", "", remaining)
    return len(remaining) == 0


def get_last_captured_sql(messages: list) -> str | None:
    """Finds the most recent SQL query stored in chat history."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("sql"):
            return m["sql"]
    return None


# --- App UI ---
st.title("💬 SAP Business One Copilot")


def handle_logout():
    """Clears conversation cache on the backend, then resets local session."""
    try:
        requests.post(
            f"{MIDDLEWARE_BASE_URL}/api/v1/clear_conversation",
            json={"session_id": "default"},
            timeout=5,
        )
    except Exception:
        pass
    st.session_state.update(
        authenticated=False,
        username=None,
        login_attempts=0,
        messages=[],
    )


if st.session_state.username:
    st.sidebar.caption(f"👤 Signed in as: **{st.session_state.username}**")

st.sidebar.button("Logout", on_click=handle_logout)
st.sidebar.divider()

if "messages" not in st.session_state:
    st.session_state.messages = []


# --- UI Helpers ---
def render_visual(visual, chart_key: str = "chart_default"):
    if not visual:
        return
    if visual.get("visual_type") == "chart" and visual.get("plotly_fig"):
        st.plotly_chart(visual["plotly_fig"], width="stretch", key=chart_key)


def render_assistant_content(m, is_latest=True, msg_idx=0):
    if m.get("is_clarification"):
        st.warning(m["content"])
    else:
        if m.get("sql"):
            if is_latest:
                with st.expander("🔍 View AI Generated SQL & Routing"):
                    st.write(f"**Tables Routed:** {', '.join(m.get('tables', []))}")
                    st.code(m["sql"], language="sql")
                    if m.get("udfs"):
                        st.write(f"**Custom UDFs Interacted:** {', '.join(m['udfs'])}")
                    else:
                        st.write("**Custom UDFs Interacted:** None")
            else:
                st.markdown("**🔍 AI Generated SQL & Routing:**")
                st.code(m["sql"], language="sql")

        st.markdown(m["content"])

        render_visual(m.get("visual"), chart_key=f"chart_hist_{msg_idx}")

        if m.get("excel_bytes"):
            st.download_button(
                label="📥 Download Full Excel Report (.xlsx)",
                data=m["excel_bytes"],
                file_name=m.get("excel_filename", f"SAP_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_excel_{msg_idx}",
            )

        if m.get("time_seconds"):
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("Execution Time", f"{m['time_seconds']} sec")
            col2.metric("Input Tokens", m.get("input_tokens", 0))
            col3.metric("Output Tokens", m.get("output_tokens", 0))


# --- Chat History Display ---
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        is_latest = i == len(st.session_state.messages) - 1

        if msg["role"] == "assistant" and not is_latest:
            with st.expander("Show Previous Response (SQL & Insight)", expanded=False):
                render_assistant_content(msg, is_latest=False, msg_idx=i)
        else:
            if msg["role"] == "assistant":
                render_assistant_content(msg, is_latest=True, msg_idx=i)
            else:
                st.write(msg["content"])

        if is_latest and msg["role"] == "assistant":
            if msg.get("is_clarification"):
                options_list = msg.get("options", [])
                if options_list:
                    cols = st.columns(len(options_list))
                    for idx, opt in enumerate(options_list):
                        if cols[idx].button(opt, key=f"clarify_{i}_{idx}"):
                            original_query = st.session_state.messages[-2]["content"]
                            st.session_state.messages.append(
                                {"role": "user", "content": f"{original_query} (Use exactly: {opt})"}
                            )
                            st.rerun()

            elif msg.get("follow_ups"):
                st.write("**Suggested Follow-ups:**")
                for idx, q in enumerate(msg["follow_ups"]):
                    if st.button(q, key=f"followup_{i}_{idx}"):
                        st.session_state.messages.append({"role": "user", "content": q})
                        st.rerun()


# --- Chat Input ---
prompt = st.chat_input("Ask about sales, stock, HR, or performance...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()


# --- Process Latest User Message ---
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_input = st.session_state.messages[-1]["content"]

    # Zero-token fast path: export the previous query directly to Excel without calling Claude
    if is_followup_export(user_input):
        last_sql = get_last_captured_sql(st.session_state.messages[:-1])
        if last_sql:
            with st.chat_message("assistant"):
                with st.spinner("Generating full Excel report from previous query..."):
                    try:
                        exp_res = requests.post(
                            f"{MIDDLEWARE_BASE_URL}/api/v1/export_excel",
                            json={"sql": last_sql},
                            timeout=120,
                        )
                        if exp_res.status_code == 200:
                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "content": "📥 Your full Excel report is ready to download below.",
                                    "sql": last_sql,
                                    "tables": ["Exported from previous query"],
                                    "excel_bytes": exp_res.content,
                                    "excel_filename": f"SAP_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                }
                            )
                            st.rerun()
                        else:
                            st.error("No data available to export to Excel.")
                            st.stop()
                    except requests.exceptions.RequestException as e:
                        st.error(f"Excel export failed: {e}")
                        st.stop()

    with st.chat_message("assistant"):
        sql_placeholder = st.empty()
        insight_placeholder = st.empty()
        visual_placeholder = st.empty()
        metrics_placeholder = st.empty()

        full_response = ""
        is_clarification = False
        options = []
        captured_sql = None
        captured_tables = []
        captured_visual = None
        captured_udfs = []
        captured_time = None
        captured_in_tokens = None
        captured_out_tokens = None
        has_backend_error = False

        with st.spinner("Analyzing intent and generating SQL..."):
            try:
                res = requests.post(
                    f"{MIDDLEWARE_BASE_URL}/api/v1/ask",
                    json={"question": user_input},
                    stream=True,
                    timeout=120,
                )
                res.raise_for_status()

                for line in res.iter_lines(chunk_size=1):
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError:
                            has_backend_error = True
                            st.error("Received an invalid response format from the server.")
                            break

                        if chunk["type"] == "metadata":
                            captured_sql = chunk.get("sql")
                            captured_tables = chunk.get("tables", [])
                            captured_udfs = chunk.get("udfs", [])
                            with sql_placeholder.expander("🔍 View AI Generated SQL & Routing"):
                                st.write(f"**Tables Routed:** {', '.join(captured_tables)}")
                                st.code(captured_sql, language="sql")
                                if captured_udfs:
                                    st.write(f"**Custom UDFs Interacted:** {', '.join(captured_udfs)}")
                                else:
                                    st.write("**Custom UDFs Interacted:** None")

                        elif chunk["type"] == "clarification_menu":
                            is_clarification = True
                            full_response = chunk.get("message", "Please clarify:")
                            options = chunk.get("options", [])
                            insight_placeholder.warning(full_response)
                            break

                        elif chunk["type"] == "chunk":
                            full_response += chunk["text"]
                            insight_placeholder.markdown(f"{full_response}▌")

                        elif chunk["type"] == "visual":
                            captured_visual = chunk.get("visual")
                            with visual_placeholder.container():
                                render_visual(captured_visual, chart_key=f"chart_live_{len(st.session_state.messages)}")

                        elif chunk["type"] == "metrics":
                            captured_time = chunk.get("time_seconds")
                            captured_in_tokens = chunk.get("input_tokens")
                            captured_out_tokens = chunk.get("output_tokens")
                            with metrics_placeholder.container():
                                st.divider()
                                col1, col2, col3 = st.columns(3)
                                col1.metric("Execution Time", f"{captured_time} sec")
                                col2.metric("Input Tokens", captured_in_tokens)
                                col3.metric("Output Tokens", captured_out_tokens)

                        elif chunk["type"] == "error":
                            st.error(chunk["text"])
                            has_backend_error = True
                            break

                if has_backend_error:
                    st.stop()

                follow_ups = []
                excel_bytes = None
                excel_filename = None

                if not is_clarification:
                    raw_lines = full_response.split("\n")
                    clean_lines = []
                    for line in raw_lines:
                        if "[BUTTON]" in line:
                            follow_ups.append(line.replace("[BUTTON]", "").strip())
                        else:
                            clean_lines.append(line)

                    full_response = "\n".join(clean_lines).strip()
                    insight_placeholder.markdown(full_response)

                    if captured_sql and wants_excel(user_input):
                        with st.spinner("Generating full Excel report..."):
                            try:
                                exp_res = requests.post(
                                    f"{MIDDLEWARE_BASE_URL}/api/v1/export_excel",
                                    json={"sql": captured_sql},
                                    timeout=120,
                                )
                                if exp_res.status_code == 200:
                                    excel_bytes = exp_res.content
                                    excel_filename = f"SAP_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                                else:
                                    st.warning("No data available to export to Excel.")
                            except requests.exceptions.RequestException as e:
                                st.warning(f"Excel export failed: {e}")

                msg_data = {
                    "role": "assistant",
                    "content": full_response,
                    "sql": captured_sql,
                    "tables": captured_tables,
                    "visual": captured_visual,
                    "udfs": captured_udfs,
                    "time_seconds": captured_time,
                    "input_tokens": captured_in_tokens,
                    "output_tokens": captured_out_tokens,
                }
                if excel_bytes:
                    msg_data["excel_bytes"] = excel_bytes
                    msg_data["excel_filename"] = excel_filename
                if is_clarification:
                    msg_data["is_clarification"] = True
                    msg_data["options"] = options
                elif follow_ups:
                    msg_data["follow_ups"] = follow_ups

                st.session_state.messages.append(msg_data)
                st.rerun()

            except requests.exceptions.RequestException as e:
                st.error(f"Backend Connection Error: {e}")