"""Fetch hourly data from MoEP Envista API and store in SQLite."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.database import classify_severity, get_connection
from src.data.loader import ISRAEL_THRESHOLDS, WHO_THRESHOLDS

ENVISTA_BASE = "https://air-papi.sviva.gov.il"
TOKEN_URL = "https://air.sviva.gov.il/Account/GetApiToken"

# Envista station ID → our OpenAQ station ID, with channel mappings
# channel IDs from the Envista /regions endpoint
STATIONS: dict[str, dict] = {
    "189": {
        "openaq_id": "4938",
        "name": "Atzmaout Haifa",
        "channels": {"NO2": 3, "CO": 4, "SO2": 22},
    },
    "86": {
        "openaq_id": "5923",
        "name": "Neve Sha'anan",
        "channels": {"NO2": 11, "O3": 13, "SO2": 8, "CO": 12},
    },
    "82": {
        "openaq_id": "6524",
        "name": "Lev Tel Aviv",
        "channels": {"NO2": 8, "O3": 5, "SO2": 1},
    },
    "36": {
        "openaq_id": "6635",
        "name": "Kikar Safra Jerusalem",
        "channels": {"NO2": 4, "O3": 5, "CO": 6},
    },
    "59": {
        "openaq_id": "11049",
        "name": "HaTzafon HaHadash (Antokolsky)",
        "channels": {"NO2": 8, "O3": 5, "SO2": 1},
    },
    "88": {
        "openaq_id": "11056",
        "name": "Merkaz HaIr Haifa",
        "channels": {"NO2": 11, "O3": 13, "SO2": 8, "CO": 12},
    },
    "184": {
        "openaq_id": "6421",
        "name": "Neot HaKikar (Dead Sea)",
        "channels": {"NO2": 18, "SO2": 2},
    },
}

# µg/m³ → ppm conversion factors at 25°C, 1 atm
# ppm = (µg/m³) / (molecular_weight × 1000 / 24.45)
# Simplified: ppm = (µg/m³) × 24.45 / (MW × 1000)
MOLECULAR_WEIGHT = {"NO2": 46.0, "O3": 48.0, "SO2": 64.1, "CO": 28.0}


def ugm3_to_ppm(pollutant: str, value: float) -> float:
    mw = MOLECULAR_WEIGHT[pollutant]
    return round(value * 24.45 / (mw * 1000), 6)


def get_api_token(client: httpx.Client) -> str:
    resp = client.post(TOKEN_URL, json={"userName": "Guest"})
    resp.raise_for_status()
    token: str = resp.text.strip().strip('"')
    return token


def fetch_channel_history(
    client: httpx.Client,
    headers: dict,
    station_id: str,
    channel_id: int,
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict]:
    resp = client.get(
        f"{ENVISTA_BASE}/v1/envista/stations/{station_id}/Average/{channel_id}",
        params={
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": to_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "fromTimebase": 60,
            "toTimebase": 60,
            "timeBeginning": "false",
            "useBackWard": "true",
            "includeSummary": "false",
            "roundType": 1,
            "unitid": -1,
            "unitConversion": "true",
        },
        headers=headers,
    )
    resp.raise_for_status()
    result: list[dict] = resp.json().get("data", [])  # type: ignore[no-any-return]
    return result


def main() -> None:
    days_back = 90
    if len(sys.argv) > 1:
        days_back = int(sys.argv[1])

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days_back)
    print(f"Fetching {days_back} days of data ({from_dt.date()} to {to_dt.date()})...")

    client = httpx.Client(timeout=60, verify=False)
    api_token = get_api_token(client)
    headers = {"Authorization": f"ApiToken {api_token}"}

    all_rows: list[tuple] = []

    for envista_id, info in STATIONS.items():
        openaq_id = info["openaq_id"]
        name = info["name"]

        for pollutant, channel_id in info["channels"].items():
            try:
                records = fetch_channel_history(
                    client, headers, envista_id, channel_id, from_dt, to_dt
                )
            except Exception as e:
                print(f"  FAIL {name} {pollutant}: {e}")
                continue

            count = 0
            for rec in records:
                channels = rec.get("channels", [])
                if not channels:
                    continue
                val = channels[0].get("value")
                if val is None:
                    continue
                ppm = ugm3_to_ppm(pollutant, float(val))
                ts_iso = pd.Timestamp(rec["datetime"], tz="UTC").isoformat()
                all_rows.append(
                    (
                        ts_iso,
                        openaq_id,
                        pollutant.lower(),
                        ppm,
                        "ppm",
                        "envista",
                    )
                )
                count += 1

            print(f"  {name:25s} | {pollutant:3s}: {count:>5} hourly readings")

    if not all_rows:
        print("No data fetched.")
        return

    # --- Insert measurements into SQLite ---
    conn = get_connection()

    before = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO measurements "
        "(timestamp, station_id, pollutant, value, unit, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        all_rows,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    new_count = after - before
    print(
        f"\nInserted {new_count} new rows "
        f"({len(all_rows)} fetched, {len(all_rows) - new_count} duplicates skipped)"
    )

    # --- Israeli exceedances for new data ---
    print("\nComputing Israeli exceedances...")
    israel_count = 0
    for pollutant, threshold in ISRAEL_THRESHOLDS.items():
        cursor = conn.execute(
            "SELECT m.id, m.timestamp, m.station_id, m.value "
            "FROM measurements m "
            "WHERE m.source = 'envista' AND m.pollutant = ? AND m.value > ? "
            "AND m.timestamp >= ? "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM exceedances_israel e WHERE e.measurement_id = m.id"
            ")",
            (pollutant, threshold, from_dt.isoformat()),
        )
        rows = []
        for mid, ts, sid, val in cursor:
            ratio = round(val / threshold, 3)
            rows.append((mid, sid, ts, pollutant, val, threshold, ratio, classify_severity(ratio)))
        if rows:
            conn.executemany(
                "INSERT INTO exceedances_israel "
                "(measurement_id, station_id, timestamp, pollutant, "
                "value, threshold, ratio, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        israel_count += len(rows)
    conn.commit()
    print(f"  {israel_count} new Israeli exceedances")

    # --- WHO exceedances (recompute for refresh window) ---
    print("Computing WHO exceedances...")
    max_window = max(w["window_hours"] for w in WHO_THRESHOLDS.values())
    window_start = (from_dt - timedelta(hours=max_window)).isoformat()

    conn.execute(
        "DELETE FROM exceedances_who WHERE window_end >= ?",
        (from_dt.isoformat(),),
    )

    who_count = 0
    for pollutant, who in WHO_THRESHOLDS.items():
        threshold = who["value"]
        window_hours = who["window_hours"]

        station_ids = conn.execute(
            "SELECT DISTINCT station_id FROM measurements "
            "WHERE pollutant = ? AND source = 'envista'",
            (pollutant,),
        ).fetchall()

        for (station_id,) in station_ids:
            df = pd.read_sql_query(
                "SELECT timestamp, value FROM measurements "
                "WHERE station_id = ? AND pollutant = ? "
                "AND timestamp >= ? ORDER BY timestamp",
                conn,
                params=(station_id, pollutant, window_start),
            )
            if df.empty:
                continue

            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").sort_index()
            avg = (
                df["value"]
                .rolling(
                    f"{window_hours}h",
                    min_periods=max(1, window_hours // 2),
                )
                .mean()
            )

            rows = []
            for ts, avg_val in avg.items():
                if pd.isna(avg_val) or avg_val <= threshold:
                    continue
                if ts < pd.Timestamp(from_dt):
                    continue
                ratio = round(avg_val / threshold, 3)
                rows.append(
                    (
                        station_id,
                        ts.isoformat(),
                        pollutant,
                        window_hours,
                        round(avg_val, 6),
                        threshold,
                        ratio,
                        classify_severity(ratio),
                    )
                )

            if rows:
                conn.executemany(
                    "INSERT INTO exceedances_who "
                    "(station_id, window_end, pollutant, window_hours, "
                    "avg_value, threshold, ratio, severity) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                who_count += len(rows)

    conn.commit()
    print(f"  {who_count} new WHO exceedances")

    # --- Summary ---
    total_meas = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    total_isr = conn.execute("SELECT COUNT(*) FROM exceedances_israel").fetchone()[0]
    total_who = conn.execute("SELECT COUNT(*) FROM exceedances_who").fetchone()[0]
    print(
        f"\nDatabase totals: {total_meas:,} measurements, "
        f"{total_isr:,} Israeli, {total_who:,} WHO exceedances"
    )
    conn.close()


if __name__ == "__main__":
    main()
