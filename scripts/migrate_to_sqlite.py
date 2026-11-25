"""One-time migration from Parquet files to SQLite."""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.database import (
    DB_PATH,
    classify_severity,
    create_tables,
    get_connection,
)
from src.data.loader import ISRAEL_THRESHOLDS, WHO_THRESHOLDS

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

ENVISTA_MAP: dict[str, str] = {
    "4938": "189",
    "5923": "86",
    "6524": "82",
    "6635": "36",
    "11049": "59",
    "11056": "88",
    "6421": "184",
}

# Correct coordinates from Envista API (MoEP).
# OpenAQ coordinates are wrong for most Israeli stations.
STATION_COORDINATES: dict[str, tuple[float, float]] = {
    "4938": (32.81707628, 35.00236365),  # Atzmaout Haifa
    "5923": (32.78746681, 35.02135697),  # Neve Sha'anan, Haifa
    "6421": (30.94577108, 35.38825659),  # Neot HaKikar, Dead Sea
    "6435": (32.10162000, 34.79550000),  # Shikun Bavli, Tel Aviv
    "6524": (32.06223440, 34.77734640),  # Tahana Merkazit, Tel Aviv
    "6635": (31.78052907, 35.22471397),  # Shprintzak, Jerusalem
    "11049": (32.08428157, 34.78260353),  # Antokolsky, Tel Aviv
    "11056": (32.81190393, 35.11309389),  # B.Eliezer, Haifa
}


def migrate_stations(conn: sqlite3.Connection) -> None:
    stations_df = pd.read_parquet(RAW_DIR / "stations.parquet")

    used_ids: set[str] = set()
    for fname in ("measurements_clean.parquet", "measurements_live.parquet"):
        path = PROCESSED_DIR / fname
        if path.exists():
            df = pd.read_parquet(path, columns=["station_id"])
            used_ids.update(df["station_id"].unique())

    stations_df = stations_df[stations_df["station_id"].isin(used_ids)]

    rows = []
    for _, r in stations_df.iterrows():
        sid = str(r["station_id"])
        name = str(r["name"])
        short = name.replace("תחנה:", "").strip() if "תחנה:" in name else name
        lat, lon = STATION_COORDINATES.get(sid, (r.get("latitude"), r.get("longitude")))
        rows.append(
            (
                sid,
                name,
                short,
                r.get("city"),
                lat,
                lon,
                r.get("pollutants"),
                ENVISTA_MAP.get(sid),
            )
        )

    conn.executemany(
        "INSERT OR IGNORE INTO stations "
        "(station_id, name, short_name, city, latitude, longitude, pollutants, envista_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    print(f"  Stations: {count} rows")


def migrate_measurements(conn: sqlite3.Connection) -> None:
    total = 0
    for fname, source in [
        ("measurements_clean.parquet", "openaq"),
        ("measurements_live.parquet", "envista"),
    ]:
        path = PROCESSED_DIR / fname
        if not path.exists():
            print(f"  Skipping {fname} (not found)")
            continue

        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df[df["is_gap"] == False]  # noqa: E712 — only real measurements
        df = df.dropna(subset=["value"])

        rows = [
            (
                row.timestamp.isoformat(),
                str(row.station_id),
                str(row.pollutant),
                round(float(row.value), 6),
                str(row.unit) if hasattr(row, "unit") else "ppm",
                source,
            )
            for row in df.itertuples(index=False)
        ]

        conn.executemany(
            "INSERT OR IGNORE INTO measurements "
            "(timestamp, station_id, pollutant, value, unit, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        print(f"  {fname}: {len(rows)} rows (source={source})")
        total += len(rows)

    print(f"  Total measurements: {total}")


def compute_exceedances_israel(conn: sqlite3.Connection) -> None:
    count = 0
    for pollutant, threshold in ISRAEL_THRESHOLDS.items():
        cursor = conn.execute(
            "SELECT id, timestamp, station_id, value "
            "FROM measurements WHERE pollutant = ? AND value > ?",
            (pollutant, threshold),
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
            print(f"  {pollutant}: {len(rows)} exceedances")
        count += len(rows)

    conn.commit()
    print(f"  Israeli exceedances total: {count}")


def compute_exceedances_who(conn: sqlite3.Connection) -> None:
    count = 0
    for pollutant, who in WHO_THRESHOLDS.items():
        threshold = who["value"]
        window_hours = who["window_hours"]

        station_rows = conn.execute(
            "SELECT DISTINCT station_id FROM measurements WHERE pollutant = ?",
            (pollutant,),
        ).fetchall()

        poll_count = 0
        for (station_id,) in station_rows:
            df = pd.read_sql_query(
                "SELECT timestamp, value FROM measurements "
                "WHERE station_id = ? AND pollutant = ? ORDER BY timestamp",
                conn,
                params=(station_id, pollutant),
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
                poll_count += len(rows)

        if poll_count:
            print(f"  {pollutant} ({window_hours}h window): {poll_count} exceedances")
        count += poll_count

    conn.commit()
    print(f"  WHO exceedances total: {count}")


def main() -> None:
    force = "--force" in sys.argv

    if DB_PATH.exists():
        if not force:
            print(f"Database already exists at {DB_PATH}")
            print("Use --force to delete and recreate.")
            return
        DB_PATH.unlink()
        print("Deleted existing database.")

    print(f"Creating database at {DB_PATH}\n")
    conn = get_connection()

    print("1. Creating tables...")
    create_tables(conn)

    print("\n2. Migrating stations...")
    migrate_stations(conn)

    print("\n3. Migrating measurements...")
    migrate_measurements(conn)

    print("\n4. Computing Israeli exceedances...")
    compute_exceedances_israel(conn)

    print("\n5. Computing WHO exceedances...")
    compute_exceedances_who(conn)

    print("\n=== Migration complete ===")
    for table in (
        "stations",
        "measurements",
        "exceedances_israel",
        "exceedances_who",
        "agent_results",
    ):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n:,} rows")

    conn.close()
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nDatabase size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
