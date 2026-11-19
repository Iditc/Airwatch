"""AirWatch Dashboard — air quality monitoring and anomaly detection for Israel."""

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).parent.parent.parent / "data"
EVENTS_DIR = DATA_DIR / "events"

ISRAEL_THRESHOLDS = {"co": 26.0, "no2": 0.106, "o3": 0.082, "so2": 0.134}
WHO_THRESHOLDS = {"co": 4.0, "no2": 0.013, "o3": 0.051, "so2": 0.015}
POLLUTANT_LABELS = {"no2": "NO₂", "o3": "O₃", "co": "CO", "so2": "SO₂"}
SEVERITY_COLORS = {"critical": "#EF4444", "high": "#F97316", "medium": "#EAB308", "low": "#22C55E"}

# OpenAQ has wrong coordinates for some Israeli stations — override with geocoded values
STATION_COORD_FIXES: dict[str, tuple[float, float]] = {
    "4938": (32.814, 34.996),  # עצמאות חיפה — Haifa, Hadar
    "5923": (32.787, 35.019),  # נ.שאנן — Haifa, Neve Sha'anan
    "6421": (30.933, 35.377),  # נאות הכיכר — Dead Sea, Arava
}

st.set_page_config(page_title="AirWatch", page_icon="🌬️", layout="wide")


@st.cache_data
def load_stations() -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "raw" / "stations.parquet")
    df["station_id"] = df["station_id"].astype(str)
    df["short_name"] = df["name"].str.replace("תחנה:", "", regex=False)
    for sid, (lat, lon) in STATION_COORD_FIXES.items():
        mask = df["station_id"] == sid
        df.loc[mask, "latitude"] = lat
        df.loc[mask, "longitude"] = lon
    return df


@st.cache_data
def load_measurements() -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "processed" / "measurements_clean.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


@st.cache_data
def load_events() -> pd.DataFrame:
    events: list[dict] = []
    if EVENTS_DIR.exists():
        for f in EVENTS_DIR.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            events.extend(data)
    return pd.DataFrame(events) if events else pd.DataFrame()


def render_sidebar(active_stations: pd.DataFrame) -> tuple[str, str]:
    st.sidebar.title("🌬️ AirWatch")
    st.sidebar.markdown("Air Quality Monitoring — Israel")
    st.sidebar.divider()

    station_map = dict(
        zip(active_stations["short_name"], active_stations["station_id"], strict=False)
    )
    selected_name = st.sidebar.selectbox("Station", list(station_map.keys()))
    selected_id = station_map[selected_name]

    pollutant = st.sidebar.selectbox(
        "Pollutant",
        ["no2", "o3", "co", "so2"],
        format_func=lambda x: POLLUTANT_LABELS[x],
    )

    st.sidebar.divider()
    st.sidebar.caption("Data: OpenAQ v3 API")
    st.sidebar.caption("Models: XGBoost (retrained 2026-11-16)")

    return selected_id, pollutant


def render_metrics(
    active_ids: list[str],
    measurements: pd.DataFrame,
    events_df: pd.DataFrame,
    station_id: str,
    pollutant: str,
) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Stations", len(active_ids))
    col2.metric("Total Readings", f"{len(measurements):,}")
    col3.metric("Anomalies", len(events_df) if not events_df.empty else 0)

    station_data = measurements[
        (measurements["station_id"] == station_id) & (measurements["pollutant"] == pollutant)
    ]
    if not station_data.empty:
        latest = station_data.sort_values("timestamp").iloc[-1]
        col4.metric(
            f"Latest {POLLUTANT_LABELS[pollutant]}",
            f"{latest['value']:.4f} {latest['unit']}",
        )


def render_map(active_stations: pd.DataFrame, selected_id: str) -> None:
    fig = px.scatter_map(
        active_stations,
        lat="latitude",
        lon="longitude",
        hover_name="short_name",
        zoom=6.5,
        center={"lat": 31.8, "lon": 34.9},
        map_style="open-street-map",
        height=500,
    )
    fig.update_traces(marker=dict(size=10, color="#3B82F6"))

    selected = active_stations[active_stations["station_id"] == selected_id]
    if not selected.empty:
        fig.add_trace(
            go.Scattermap(
                lat=selected["latitude"],
                lon=selected["longitude"],
                mode="markers",
                marker=dict(size=18, color="#EF4444"),
                name="Selected",
                showlegend=False,
            )
        )

    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, use_container_width=True)


def render_timeseries(
    measurements: pd.DataFrame, station_id: str, pollutant: str, station_name: str
) -> None:
    data = measurements[
        (measurements["station_id"] == station_id) & (measurements["pollutant"] == pollutant)
    ].sort_values("timestamp")

    if data.empty:
        st.info("No data for this station and pollutant.")
        return

    fig = px.line(data, x="timestamp", y="value", height=500)
    fig.update_traces(line=dict(width=1, color="#3B82F6"))

    if pollutant in ISRAEL_THRESHOLDS:
        fig.add_hline(
            y=ISRAEL_THRESHOLDS[pollutant],
            line_dash="dash",
            line_color="#EF4444",
            annotation_text="Israel limit",
        )
    if pollutant in WHO_THRESHOLDS:
        fig.add_hline(
            y=WHO_THRESHOLDS[pollutant],
            line_dash="dot",
            line_color="#F97316",
            annotation_text="WHO guideline",
        )

    fig.update_layout(
        xaxis_title="",
        yaxis_title=f"{POLLUTANT_LABELS[pollutant]} ({data.iloc[0]['unit']})",
        margin=dict(l=0, r=0, t=0, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_events(events_df: pd.DataFrame) -> None:
    if events_df.empty:
        st.info("No anomaly events detected yet.")
        return

    display_cols = [
        "station_name",
        "pollutant",
        "severity",
        "value",
        "baseline_value",
        "anomaly_score",
        "timestamp",
    ]
    available = [c for c in display_cols if c in events_df.columns]
    df = events_df[available].sort_values("timestamp", ascending=False).copy()

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df["date"] = ts.dt.strftime("%Y-%m-%d")
        df["time"] = ts.dt.strftime("%H:%M")
        df = df.drop(columns=["timestamp"])

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "anomaly_score": st.column_config.ProgressColumn(
                "Anomaly Score", min_value=0, max_value=1, format="%.2f"
            ),
            "severity": st.column_config.TextColumn("Severity"),
        },
    )


def main() -> None:
    stations = load_stations()
    measurements = load_measurements()
    events_df = load_events()

    active_ids = measurements["station_id"].unique().tolist()
    active_stations = stations[stations["station_id"].isin(active_ids)]

    selected_id, pollutant = render_sidebar(active_stations)
    selected_name = active_stations.loc[
        active_stations["station_id"] == selected_id, "short_name"
    ].iloc[0]

    render_metrics(active_ids, measurements, events_df, selected_id, pollutant)

    st.divider()
    map_col, chart_col = st.columns([1, 2])

    with map_col:
        st.subheader("📍 Stations")
        render_map(active_stations, selected_id)

    with chart_col:
        st.subheader(f"📈 {POLLUTANT_LABELS[pollutant]} — {selected_name}")
        render_timeseries(measurements, selected_id, pollutant, selected_name)

    st.divider()
    st.subheader("🚨 Anomaly Events")
    render_events(events_df)


if __name__ == "__main__":
    main()
