# AirWatch — API & Database Reference

עינת, זה המסמך המעודכן עם כל ה-endpoints ומבנה ה-DB.
עודכן: 2026-11-22.

---

## Database — SQLite

כל הנתונים נמצאים בקובץ אחד: `data/airwatch.db` (SQLite, WAL mode).

### טבלאות

```
stations                    measurements
┌──────────────────┐       ┌──────────────────────────┐
│ station_id  PK   │◄──────│ station_id  FK            │
│ name             │       │ id  PK (autoincrement)    │
│ short_name       │       │ timestamp                 │
│ city             │       │ pollutant (no2/o3/co/so2) │
│ latitude         │       │ value (ppm)               │
│ longitude        │       │ unit                      │
│ pollutants       │       │ source (openaq/envista)   │
│ envista_id       │       │ UNIQUE(timestamp,         │
└──────────────────┘       │   station_id, pollutant)  │
                           └──────────────────────────┘
                                      │
              ┌───────────────────────┼──────────────────────┐
              ▼                       ▼                      ▼
exceedances_israel          exceedances_who          agent_results
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│ id  PK          │    │ id  PK           │    │ id  PK               │
│ measurement_id  │    │ station_id  FK   │    │ exceedance_type       │
│ station_id  FK  │    │ window_end       │    │   ('israel' / 'who') │
│ timestamp       │    │ pollutant        │    │ exceedance_id         │
│ pollutant       │    │ window_hours     │    │ agent_type            │
│ value           │    │ avg_value        │    │   ('root_cause' /     │
│ threshold       │    │ threshold        │    │    'alert' /          │
│ ratio           │    │ ratio            │    │    'sensor_health')   │
│ severity        │    │ severity         │    │ created_at            │
└─────────────────┘    └──────────────────┘    │ result_json (TEXT)    │
                                               └──────────────────────┘
```

### severity

ה-severity מחושב לפי ratio (ערך / סף):
- `low` — ratio < 1.5
- `medium` — ratio 1.5–2.0
- `high` — ratio >= 2.0

### כמויות נוכחיות

| טבלה | שורות |
|------|-------|
| stations | 8 |
| measurements | ~252K |
| exceedances_israel | ~823 |
| exceedances_who | ~29.5K |
| agent_results | 0 (ריקה — מחכה ל-agents שלך) |

---

## API Endpoints

Base URL: `http://localhost:8000`

Swagger docs: `http://localhost:8000/docs`

### GET /health

סטטוס השרת.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2026-11-22T13:07:59Z",
  "stations_monitored": 8,
  "last_detection_run": null
}
```

### GET /stations

רשימת כל התחנות שיש עליהן מדידות.

```json
[
  {
    "station_id": "6524",
    "name": "תחנה מרכזית תל אביב",
    "city": "Unknown",
    "latitude": 32.05602,
    "longitude": 34.77903,
    "pollutants": ["co", "no2", "o3", "so2"]
  }
]
```

### GET /readings

מדידות שעתיות לפי תחנה.

| פרמטר | חובה | תיאור |
|-------|------|-------|
| station_id | כן | מזהה תחנה |
| pollutant | לא | סינון לפי מזהם (no2/o3/co/so2) |
| limit | לא | מקסימום שורות (ברירת מחדל: 200, מקסימום: 5000) |

```
GET /readings?station_id=6524&pollutant=no2&limit=3
```

```json
[
  {
    "station_id": "6524",
    "timestamp": "2026-11-22T10:00:00Z",
    "pollutant": "no2",
    "value": 0.007441,
    "unit": "ppm"
  }
]
```

### GET /exceedances/israel

חריגות מסף איכות אוויר ישראלי (ערך שעתי מעל הסף).

| פרמטר | חובה | תיאור |
|-------|------|-------|
| station_id | לא | סינון לפי תחנה |
| pollutant | לא | סינון לפי מזהם |
| severity | לא | סינון לפי חומרה (low/medium/high) |
| limit | לא | ברירת מחדל: 200 |

ספים ישראליים (ppm): NO2=0.106, O3=0.082, SO2=0.134, CO=26.0

```json
[
  {
    "id": 814,
    "measurement_id": 252213,
    "station_id": "5923",
    "timestamp": "2026-11-22T03:00:00Z",
    "pollutant": "o3",
    "value": 0.089446,
    "threshold": 0.082,
    "ratio": 1.091,
    "severity": "low"
  }
]
```

### GET /exceedances/who

חריגות מהנחיות WHO 2021 (ממוצע רץ מעל הסף).

פרמטרים — זהים ל-`/exceedances/israel`.

ספי WHO (ppm, ממוצע רץ): NO2=0.013 (24h), O3=0.051 (8h), SO2=0.015 (24h), CO=4.0 (24h)

```json
[
  {
    "id": 29813,
    "station_id": "6524",
    "window_end": "2026-11-20T20:00:00Z",
    "pollutant": "no2",
    "window_hours": 24,
    "avg_value": 0.026131,
    "threshold": 0.013,
    "ratio": 2.01,
    "severity": "high"
  }
]
```

### GET /agent-results

תוצאות של ה-agents (Root Cause / Alert / Sensor Health).

| פרמטר | חובה | תיאור |
|-------|------|-------|
| exceedance_type | לא | israel / who |
| exceedance_id | לא | מזהה החריגה |
| agent_type | לא | root_cause / alert / sensor_health |
| limit | לא | ברירת מחדל: 100 |

**הטבלה כרגע ריקה.** כשתבני agent, הוא צריך לכתוב ל-DB ככה:

```python
from src.data.database import get_connection
import json

conn = get_connection()
conn.execute(
    "INSERT INTO agent_results "
    "(exceedance_type, exceedance_id, agent_type, created_at, result_json) "
    "VALUES (?, ?, ?, ?, ?)",
    ("israel", 814, "root_cause", "2026-11-22T14:00:00Z",
     json.dumps({"probable_cause": "Industrial activity", "confidence": 0.85})),
)
conn.commit()
conn.close()
```

### GET /stations/{station_id}/health

מצב תחנה — מתי דיווחה לאחרונה, זמינות, מזהמים פעילים.

```
GET /stations/6524/health
```

```json
{
  "station_id": "6524",
  "name": "תחנה מרכזית תל אביב",
  "last_reading": "2026-11-22T10:00:00Z",
  "hours_since_last": 4.2,
  "total_readings": 31250,
  "pollutants_active": ["no2", "o3", "so2"],
  "coverage_pct": 98.5
}
```

### GET /anomalies

אירועי אנומליה מזיהוי ML (Isolation Forest / Autoencoder).

```json
[
  {
    "event_id": "evt_20261120_6524_no2",
    "station_id": "6524",
    "station_name": "תחנה מרכזית תל אביב",
    "timestamp": "2026-11-20T14:00:00Z",
    "pollutant": "no2",
    "value": 0.045,
    "baseline_value": 0.012,
    "anomaly_score": 0.92,
    "severity": "high",
    "detection_method": "isolation_forest",
    "latitude": 32.05602,
    "longitude": 34.77903
  }
]
```

### GET /thresholds

ספי זיהום (ישראלי + WHO).

```json
{
  "israel": {"co": 26.0, "no2": 0.106, "o3": 0.082, "so2": 0.134},
  "who": {
    "co": {"value": 4.0, "window_hours": 24},
    "no2": {"value": 0.013, "window_hours": 24},
    "o3": {"value": 0.051, "window_hours": 8},
    "so2": {"value": 0.015, "window_hours": 24}
  }
}
```

---

## הרצת השרת

```bash
cd Airwatch
.venv\Scripts\activate
python -m uvicorn src.api.main:app --port 8000 --reload
```

ואז: http://localhost:8000/docs

---

## שינויים מאז ה-onboarding

כמה דברים השתנו מאז המסמך הראשון:

1. **SQLite במקום Parquet** — כל הנתונים עברו ל-`data/airwatch.db`. הקוד קורא מ-SQLite דרך `src/data/database.py`. לא צריך לטעון Parquet files.

2. **מקור נתונים נוסף** — מעבר ל-OpenAQ (נתונים היסטוריים 2017–2019), יש עכשיו גם Envista API (נתונים חיים מנובמבר 2026). ב-DB שניהם מופיעים כשורות בטבלת `measurements` עם `source` שונה.

3. **Exceedance endpoints חדשים** — `/exceedances/israel` ו-`/exceedances/who` לא היו ב-API המקורי.

4. **agent_results** — הטבלה הזו היא הממשק בין ה-agents שלך ל-dashboard. ה-agents כותבים אליה, ה-dashboard קורא ממנה דרך `/agent-results`.

5. **agent_io.py — שימי לב** — ה-schemas ב-`src/schemas/agent_io.py` (כמו `InvestigationRequest`) משתמשים ב-`event_id` ו-`anomaly_score` שמתאימים לאנומליות ML. אבל טבלת `agent_results` ב-DB מקשרת לחריגות דרך `exceedance_type` + `exceedance_id`. כשתבני את ה-agents, תצטרכי להחליט אם הם עובדים עם exceedances (מה-DB), עם anomalies (מ-ML), או עם שניהם. נדבר על זה.
