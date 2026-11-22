"""Fetch active fire hotspots from NASA FIRMS and store in SQLite."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.database import create_tables, get_connection
from src.data.firms_client import fetch_hotspots, find_nearby_fires


def main() -> None:
    days = 5
    if len(sys.argv) > 1:
        days = int(sys.argv[1])

    print(f"Fetching FIRMS fire data ({days} days)...")
    hotspots = fetch_hotspots(days=days)
    print(f"  {len(hotspots)} hotspots inside Israel (+10 km buffer)")

    if not hotspots:
        print("No fire data.")
        return

    conn = get_connection()
    create_tables(conn)

    rows = []
    for h in hotspots:
        rows.append(
            (
                float(h["latitude"]),
                float(h["longitude"]),
                h["acq_date"],
                h["acq_time"],
                h["satellite"],
                h.get("confidence", "nominal"),
                float(h["frp"]) if h.get("frp") else None,
                float(h["bright_ti4"]) if h.get("bright_ti4") else None,
                h.get("daynight", ""),
                h["source"],
            )
        )

    before = conn.execute("SELECT COUNT(*) FROM fire_hotspots").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO fire_hotspots "
        "(latitude, longitude, acq_date, acq_time, satellite, "
        "confidence, frp, bright_ti4, daynight, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM fire_hotspots").fetchone()[0]
    new_count = after - before
    print(f"  Inserted {new_count} new hotspots ({len(rows) - new_count} duplicates)")

    # Show fires near each station
    print("\nFires near monitoring stations (50 km radius):")
    stations = conn.execute(
        "SELECT station_id, short_name, latitude, longitude FROM stations"
    ).fetchall()

    for s in stations:
        nearby = find_nearby_fires(hotspots, s["latitude"], s["longitude"], radius_km=50.0)
        if nearby:
            high = [f for f in nearby if f.get("confidence") == "high"]
            closest = nearby[0]["distance_km"]
            print(
                f"  {s['short_name']:25s} | "
                f"{len(nearby)} fires, {len(high)} high-confidence, "
                f"closest {closest} km"
            )

    total = conn.execute("SELECT COUNT(*) FROM fire_hotspots").fetchone()[0]
    print(f"\nTotal fire hotspots in DB: {total}")
    conn.close()


if __name__ == "__main__":
    main()
