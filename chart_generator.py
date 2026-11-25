import json
import re
import pandas as pd
import plotly.express as px


def _parse_number(val: str):
    """Converts formatted summary values (₹, %, K/L/Cr, commas) into floats."""
    if not isinstance(val, str):
        return None

    bracket_match = re.search(r"\(([^)]+)\)", val)
    token = bracket_match.group(1) if bracket_match else val
    cleaned = re.sub(r"[₹$,%\s,]", "", token).strip()

    multiplier = 1.0
    if cleaned.lower().endswith("cr"):
        multiplier, cleaned = 1e7, cleaned[:-2]
    elif cleaned.lower().endswith("l"):
        multiplier, cleaned = 1e5, cleaned[:-1]
    elif cleaned.lower().endswith("k"):
        multiplier, cleaned = 1e3, cleaned[:-1]

    try:
        return round(float(cleaned) * multiplier, 2)
    except ValueError:
        return None


def build_plotly_figure(df: pd.DataFrame, chart_type: str, x_col: str, y_cols: list[str]):
    """Builds a Plotly figure JSON dict compatible with both Streamlit and React.js."""
    print(f"\n--- STEP 3: SENDING TO PLOTLY ({chart_type.upper()}) ---")
    print(f"X-Axis: {x_col} | Y-Axis: {y_cols}")
    print(df.to_string(index=False))

    if chart_type == "line":
        fig = px.line(df, x=x_col, y=y_cols, markers=True)
    elif chart_type == "pie":
        fig = px.pie(df, names=x_col, values=y_cols[0])
    else:
        fig = px.bar(df, x=x_col, y=y_cols, barmode="group")

    # Prevents Plotly from converting large floats to 'M' or 'B' (shows full numbers instead)
    if chart_type != "pie":
        fig.update_yaxes(tickformat=",.0f", tickprefix="₹")

    fig.update_layout(margin=dict(l=20, r=20, t=30, b=20))
    plotly_json = json.loads(fig.to_json())

    print("\n--- STEP 4: PLOTLY JSON TRACES (x & y values sent to UI) ---")
    for trace in plotly_json.get("data", []):
        print({
            "type": trace.get("type"),
            "name": trace.get("name"),
            "x_or_labels": trace.get("x") or trace.get("labels"),
            "y_or_values": trace.get("y") or trace.get("values"),
        })
    print("-------------------------------------------------------------\n")

    return plotly_json


def build_chart_from_summary(summary_text: str):
    """Extracts a Markdown table from the summary and returns a dynamic chart config + Plotly JSON."""
    lines = [
        ln.strip()
        for ln in (summary_text or "").splitlines()
        if ln.strip().startswith("|") and ln.strip().endswith("|")
    ]
    if len(lines) < 4:
        print("\n--- CHART DEBUG: No valid Markdown table found in summary. Skipping chart. ---\n")
        return None

    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    data_rows = []
    for ln in lines[2:]:
        if set(ln.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) == len(headers):
            data_rows.append(cells)

    if len(data_rows) < 2:
        return None

    df = pd.DataFrame(data_rows, columns=headers)
    print("\n--- STEP 1: RAW PANDAS DATAFRAME (FROM MARKDOWN TABLE) ---")
    print(df.to_string(index=False))

    num_cols = []
    for col in df.columns[1:]:
        parsed = df[col].apply(_parse_number)
        if parsed.notna().all():
            df[col] = parsed
            num_cols.append(col)

    if not num_cols:
        print(" No numeric columns could be parsed. Skipping chart.")
        return None

    print("\n--- STEP 2: PARSED NUMERIC DATAFRAME (FLOATS) ---")
    print(df.to_string(index=False))
    print("Data Types:\n", df.dtypes.to_string())

    x_col = df.columns[0]
    y_cols = num_cols[:2]
    row_count = len(df)
    plot_df = df[[x_col] + y_cols]

    # Automatically detect if the X-axis contains dates/periods
    parsed_dates = pd.to_datetime(df[x_col], errors="coerce", format="mixed")
    is_time_series = parsed_dates.notna().mean() >= 0.8

    if is_time_series:
        default_type, allowed = "line", ["line", "bar", "area", "table"]
    elif row_count <= 6 and len(y_cols) == 1:
        default_type, allowed = "pie", ["pie", "bar", "table"]
    elif row_count <= 15:
        default_type, allowed = "bar", ["bar", "line", "table"]
    else:
        default_type, allowed = "bar", ["table", "bar"]
        plot_df = plot_df.head(15)

    plotly_fig = build_plotly_figure(plot_df, default_type, x_col, y_cols)

    return {
        "default_type": default_type,
        "allowed_types": allowed,
        "x_key": x_col,
        "y_keys": y_cols,
        "total_rows": row_count,
        "data": plot_df.to_dict(orient="records"),
        "full_data": df[[x_col] + y_cols].to_dict(orient="records"),
        "plotly_fig": plotly_fig,
    }


def build_visual_from_summary(summary_text: str):
    """Main entry point: returns a chart payload (with Plotly JSON) or None."""
    chart_payload = build_chart_from_summary(summary_text)
    if chart_payload:
        return {
            "visual_type": "chart",
            "chart": chart_payload,
            "plotly_fig": chart_payload["plotly_fig"],
        }

    return None