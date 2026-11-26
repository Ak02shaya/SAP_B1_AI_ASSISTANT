import json
import re
import pandas as pd
import plotly.express as px


# --- 1. Zero-Token Keyword Rules ---
TREND_KEYWORDS = re.compile(
    r"\b(trend|trends|over time|timeline|progression|trajectory|history|historical|"
    r"daily|day[\s-]?wise|day by day|weekly|week[\s-]?wise|monthly|month[\s-]?wise|"
    r"month by month|quarterly|quarter[\s-]?wise|yearly|annual|annually|year[\s-]?wise|"
    r"year by year|last\s+\d+\s+(day|days|week|weeks|month|months|year|years)|"
    r"last\s+(two|three|four|five|six|seven|ten)\s+(days|weeks|months|years)|"
    r"previous\s+(day|days|week|weeks|month|months|year|years)|"
    r"past\s+\d+\s+(day|days|week|weeks|month|months|year|years)|yoy|mom|wow)\b",
    re.IGNORECASE,
)

COMPARE_KEYWORDS = re.compile(
    r"\b(compare|comparison|vs\.?|versus|against|difference|variance|"
    r"profit|loss|margin|growth|target|actual|budget|performance|before and after)\b",
    re.IGNORECASE,
)

SHARE_KEYWORDS = re.compile(
    r"\b(share|distribution|mix|split|contribution|composition|proportion|pie)\b",
    re.IGNORECASE,
)

BREAKDOWN_KEYWORDS = re.compile(
    r"\b(by\s+(brand|category|customer|client|item|product|vendor|supplier|"
    r"region|state|city|branch|warehouse|salesperson|employee|department|group)|"
    r"top|bottom|highest|lowest|best|worst|leading|rank|ranking|breakdown|wise)\b",
    re.IGNORECASE,
)

EXPLICIT_CHART_KEYWORDS = re.compile(
    r"\b(chart|graph|plot|visual|visualize|visualise|diagram|bar|line|pie|area)\b",
    re.IGNORECASE,
)

# Skip charts on pure single-entity lookups unless user explicitly asks for a chart
LOOKUP_ONLY_KEYWORDS = re.compile(
    r"\b(address|gstin|gst\s*no|pan\s*no|barcode|email|contact\s*details|phone\s*number|mobile\s*number)\b",
    re.IGNORECASE,
)

# --- 2. Column Classification Rules (Prevents IDs/Mobile/% from corrupting ₹ axes) ---
NON_METRIC_COL_RE = re.compile(
    r"\b(id|code|no|num|docnum|docentry|invoice|mobile|phone|contact|pin|zip|pincode|"
    r"gst|pan|hsn|sac|sr|sno|sl|date|year|month)\b",
    re.IGNORECASE,
)
PCT_COL_RE = re.compile(r"(%|share|percent|pct|ratio|margin|growth)", re.IGNORECASE)
COUNT_COL_RE = re.compile(
    r"\b(qty|quantity|count|units|pcs|nos|orders|invoices|customers|items|stock|days|employees)\b",
    re.IGNORECASE,
)


def _parse_number(val: str):
    """Converts formatted summary values (₹, %, K/L/Cr, negatives, commas) into floats."""
    if not isinstance(val, str):
        return None

    text = val.strip()
    is_negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))

    # Extract full Indian-grouped number inside brackets e.g. "₹12.5 L (₹12,50,000)" -> "₹12,50,000"
    bracket_match = re.search(r"\(([^)]+)\)", text)
    if bracket_match and not text.startswith("("):
        token = bracket_match.group(1)
    else:
        token = text

    cleaned = re.sub(r"[₹$,%\s,()]", "", token).strip()

    multiplier = 1.0
    if cleaned.lower().endswith("cr"):
        multiplier, cleaned = 1e7, cleaned[:-2]
    elif cleaned.lower().endswith("l"):
        multiplier, cleaned = 1e5, cleaned[:-1]
    elif cleaned.lower().endswith("k"):
        multiplier, cleaned = 1e3, cleaned[:-1]

    try:
        num = round(float(cleaned) * multiplier, 2)
        if is_negative and num > 0:
            num = -num
        return num
    except ValueError:
        return None


def _short_label(label: str, max_len: int = 26) -> str:
    """Truncates long category names on axes so labels never overlap."""
    s = str(label).strip()
    return s if len(s) <= max_len else s[: max_len - 3].rstrip() + "..."


def _classify_numeric_columns(df: pd.DataFrame):
    """Separates parsed numeric columns into Currency, Count, and Percentage groups."""
    currency_cols, count_cols, pct_cols = [], [], []

    for col in df.columns[1:]:
        if NON_METRIC_COL_RE.search(str(col)):
            continue

        parsed = df[col].apply(_parse_number)
        if parsed.notna().mean() >= 0.8 and parsed.notna().sum() >= 2:
            df[col] = parsed.fillna(0.0)
            col_str = str(col)
            if PCT_COL_RE.search(col_str):
                pct_cols.append(col)
            elif COUNT_COL_RE.search(col_str):
                count_cols.append(col)
            else:
                currency_cols.append(col)

    # Pick one consistent scale family so ₹ lakhs and % shares never clash on the same axis
    if currency_cols:
        return currency_cols[:2], "currency"
    if count_cols:
        return count_cols[:2], "count"
    if pct_cols:
        return pct_cols[:2], "percent"
    return [], None


def _detect_chart_intent(user_prompt: str, df: pd.DataFrame, x_col: str, y_cols: list[str], metric_unit: str):
    """Selects the cleanest chart type and title from user keywords + data shape (0 tokens)."""
    prompt = (user_prompt or "").strip()
    row_count = len(df)
    avg_label_len = df[x_col].astype(str).str.len().mean()

    parsed_dates = pd.to_datetime(df[x_col], errors="coerce", format="mixed")
    is_time_series = parsed_dates.notna().mean() >= 0.8

    has_trend = bool(TREND_KEYWORDS.search(prompt)) or is_time_series
    has_compare = bool(COMPARE_KEYWORDS.search(prompt))
    has_share = bool(SHARE_KEYWORDS.search(prompt))
    has_breakdown = bool(BREAKDOWN_KEYWORDS.search(prompt))

    # Build a clean human-readable title
    metric_label = " vs ".join(y_cols)
    chart_title = f"{metric_label} by {x_col}"

    # 1. Time-series / Trend -> Line (or Area if explicitly requested)
    if has_trend:
        chart_type = "area" if re.search(r"\barea\b", prompt, re.IGNORECASE) else "line"
        allowed = ["line", "area", "bar", "table"]
        return chart_type, allowed, f"{metric_label} Trend ({x_col})"

    # 2. Share / Distribution -> Donut Pie (strictly capped at 6 slices with positive values)
    if has_share and row_count <= 6 and len(y_cols) == 1 and (df[y_cols[0]] >= 0).all():
        return "pie", ["pie", "hbar", "bar", "table"], f"{metric_label} Share by {x_col}"

    # 3. Multi-metric Comparison (e.g., Profit vs Loss, Sales vs Target, Brand A vs Brand B)
    if has_compare and len(y_cols) >= 2:
        return "grouped_bar", ["grouped_bar", "bar", "line", "table"], f"{metric_label} Comparison"

    # 4. Category / Brand / Top-N Breakdown -> Horizontal Bar when labels are long or rows > 6
    use_horizontal = (avg_label_len > 11 or row_count > 6) and len(y_cols) == 1
    if has_breakdown or has_compare or row_count >= 3:
        if use_horizontal:
            return "hbar", ["hbar", "bar", "pie", "table"], chart_title
        if row_count <= 5 and len(y_cols) == 1 and not has_compare and (df[y_cols[0]] >= 0).all():
            return "pie", ["pie", "bar", "hbar", "table"], chart_title
        return "bar", ["bar", "hbar", "line", "table"], chart_title

    # Fallback for 2-row comparisons
    return ("hbar" if use_horizontal else "bar"), ["bar", "hbar", "table"], chart_title


def build_plotly_figure(
    df: pd.DataFrame,
    chart_type: str,
    x_col: str,
    y_cols: list[str],
    metric_unit: str = "currency",
    title: str = "",
):
    """Builds a clean, non-overlapping Plotly figure JSON dict."""
    plot_df = df.copy()
    plot_df["_full_label"] = plot_df[x_col].astype(str)
    plot_df["_display_label"] = plot_df[x_col].apply(lambda v: _short_label(v, 26))

    row_count = len(plot_df)
    show_legend = len(y_cols) > 1 or chart_type == "pie"

    # Configure value formatting by metric unit
    if metric_unit == "currency":
        tick_prefix, tick_suffix, tick_fmt = "₹", "", ",.0f"
    elif metric_unit == "percent":
        tick_prefix, tick_suffix, tick_fmt = "", "%", ",.1f"
    else:
        tick_prefix, tick_suffix, tick_fmt = "", "", ",.0f"

    if chart_type == "line":
        fig = px.line(
            plot_df,
            x="_display_label",
            y=y_cols,
            markers=True,
            title=title,
            hover_data={"_full_label": True, "_display_label": False},
        )
        fig.update_traces(line=dict(width=3), marker=dict(size=8))

    elif chart_type == "area":
        fig = px.area(
            plot_df,
            x="_display_label",
            y=y_cols,
            title=title,
            hover_data={"_full_label": True, "_display_label": False},
        )

    elif chart_type == "pie":
        fig = px.pie(
            plot_df,
            names="_display_label",
            values=y_cols[0],
            hole=0.42,
            title=title,
            hover_data={"_full_label": True},
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent",
            insidetextorientation="horizontal",
        )

    elif chart_type == "hbar":
        # Horizontal bar: eliminates overlapping X-axis labels for customer/brand/item names
        fig = px.bar(
            plot_df,
            x=y_cols[0],
            y="_display_label",
            orientation="h",
            title=title,
            hover_data={"_full_label": True, "_display_label": False},
        )
        fig.update_yaxes(autorange="reversed", title_text="", automargin=True)
        fig.update_xaxes(
            title_text=y_cols[0],
            tickprefix=tick_prefix,
            ticksuffix=tick_suffix,
            tickformat=tick_fmt,
            automargin=True,
        )

    else:  # "bar" or "grouped_bar"
        fig = px.bar(
            plot_df,
            x="_display_label",
            y=y_cols,
            barmode="group",
            title=title,
            hover_data={"_full_label": True, "_display_label": False},
        )

    # Anti-overlap layout rules for standard vertical X/Y charts
    if chart_type in ("bar", "grouped_bar", "line", "area"):
        max_lbl = plot_df["_display_label"].str.len().max()
        tick_angle = -35 if (max_lbl > 8 or row_count > 5) else 0
        fig.update_xaxes(
            title_text="",
            tickangle=tick_angle,
            automargin=True,
        )
        fig.update_yaxes(
            title_text=y_cols[0] if len(y_cols) == 1 else "",
            tickprefix=tick_prefix,
            ticksuffix=tick_suffix,
            tickformat=tick_fmt,
            automargin=True,
        )

    dynamic_height = max(350, min(600, row_count * 42 + 130)) if chart_type == "hbar" else 400

    fig.update_layout(
        height=dynamic_height,
        showlegend=show_legend,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        uniformtext_minsize=11,
        uniformtext_mode="hide",
        hovermode="closest" if chart_type in ("pie", "hbar") else "x unified",
        title=dict(x=0.0, xanchor="left", font=dict(size=16)),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            title_text="",
        ),
        margin=dict(l=20, r=25, t=65, b=30),
    )

    return json.loads(fig.to_json())


def build_chart_from_summary(summary_text: str, user_prompt: str = ""):
    """Extracts a Markdown table and generates a keyword-matched, non-overlapping chart."""
    prompt = (user_prompt or "").strip()

    # Skip charts on pure lookup queries unless the user explicitly asked for a visual
    if prompt and LOOKUP_ONLY_KEYWORDS.search(prompt) and not EXPLICIT_CHART_KEYWORDS.search(prompt):
        return None

    lines = [
        ln.strip()
        for ln in (summary_text or "").splitlines()
        if ln.strip().startswith("|") and ln.strip().endswith("|")
    ]
    if len(lines) < 4:
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

    y_cols, metric_unit = _classify_numeric_columns(df)
    if not y_cols:
        return None

    x_col = df.columns[0]
    row_count = len(df)
    plot_df = df[[x_col] + y_cols].head(12)

    chart_type, allowed, title = _detect_chart_intent(prompt, plot_df, x_col, y_cols, metric_unit)
    plotly_fig = build_plotly_figure(plot_df, chart_type, x_col, y_cols, metric_unit, title)

    return {
        "default_type": chart_type,
        "allowed_types": allowed,
        "x_key": x_col,
        "y_keys": y_cols,
        "metric_unit": metric_unit,
        "total_rows": row_count,
        "data": plot_df.to_dict(orient="records"),
        "full_data": df[[x_col] + y_cols].to_dict(orient="records"),
        "plotly_fig": plotly_fig,
    }


def build_visual_from_summary(summary_text: str, user_prompt: str = ""):
    """Main entry point: returns a chart payload (with Plotly JSON) or None."""
    chart_payload = build_chart_from_summary(summary_text, user_prompt=user_prompt)
    if chart_payload:
        return {
            "visual_type": "chart",
            "chart": chart_payload,
            "plotly_fig": chart_payload["plotly_fig"],
        }
    return None