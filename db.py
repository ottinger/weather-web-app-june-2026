import json
import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

_db_user = os.environ.get('DB_USER')
_db_password = os.environ.get('DB_PASSWORD')
DATABASE_URL = os.environ.get('DATABASE_URL', f'postgresql://{_db_user}:{_db_password}@localhost/weather')

_CREATE_CITIES = """
CREATE TABLE IF NOT EXISTS cities (
    id           SERIAL PRIMARY KEY,
    display_name TEXT NOT NULL UNIQUE,
    lat          DOUBLE PRECISION NOT NULL,
    lon          DOUBLE PRECISION NOT NULL,
    nws_city     TEXT,
    nws_state    TEXT,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_WEATHER_RESULTS = """
CREATE TABLE IF NOT EXISTS weather_results (
    id               SERIAL PRIMARY KEY,
    city_id          INTEGER NOT NULL REFERENCES cities(id),
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_temp     INTEGER,
    current_unit     TEXT,
    current_forecast TEXT,
    wind_speed       TEXT,
    wind_direction   TEXT,
    precip           INTEGER,
    periods          JSONB NOT NULL,
    hourly           JSONB NOT NULL
)
"""

_CREATE_LOOKUPS = """
CREATE TABLE IF NOT EXISTS lookups (
    id                SERIAL PRIMARY KEY,
    query             TEXT NOT NULL,
    searched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    city_id           INTEGER REFERENCES cities(id),
    weather_result_id INTEGER REFERENCES weather_results(id),
    success           BOOLEAN NOT NULL,
    error_message     TEXT
)
"""


@contextmanager
def _conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_CITIES)
            cur.execute(_CREATE_WEATHER_RESULTS)
            cur.execute(_CREATE_LOOKUPS)


def upsert_city(display_name, lat, lon, nws_city, nws_state):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cities (display_name, lat, lon, nws_city, nws_state)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (display_name) DO UPDATE
                    SET lat       = EXCLUDED.lat,
                        lon       = EXCLUDED.lon,
                        nws_city  = EXCLUDED.nws_city,
                        nws_state = EXCLUDED.nws_state
                RETURNING id
                """,
                (display_name, lat, lon, nws_city, nws_state),
            )
            return cur.fetchone()[0]


def save_weather_result(city_id, weather):
    current = weather['current']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO weather_results
                    (city_id, current_temp, current_unit, current_forecast,
                     wind_speed, wind_direction, precip, periods, hourly)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    city_id,
                    current.get('temperature'),
                    current.get('temperatureUnit'),
                    current.get('shortForecast'),
                    current.get('windSpeed'),
                    current.get('windDirection'),
                    current.get('precip'),
                    json.dumps(weather['periods']),
                    json.dumps(weather['hourly']),
                ),
            )
            return cur.fetchone()[0]


def save_lookup(query, *, city_id=None, weather_result_id=None, success, error_message=None):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lookups
                    (query, city_id, weather_result_id, success, error_message)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (query, city_id, weather_result_id, success, error_message),
            )


def get_recent_lookups(limit=5):
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    l.query,
                    l.searched_at,
                    l.success,
                    l.error_message,
                    c.nws_city,
                    c.nws_state,
                    c.display_name,
                    wr.current_temp,
                    wr.current_unit,
                    wr.current_forecast
                FROM lookups l
                LEFT JOIN cities c ON l.city_id = c.id
                LEFT JOIN weather_results wr ON l.weather_result_id = wr.id
                ORDER BY l.searched_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]


def get_lookup_history(page=1, per_page=50, query_filter='', status_filter='all'):
    offset = (page - 1) * per_page
    conditions = []
    params = []

    if query_filter:
        conditions.append('l.query ILIKE %s')
        params.append(f'%{query_filter}%')
    if status_filter == 'success':
        conditions.append('l.success = TRUE')
    elif status_filter == 'failed':
        conditions.append('l.success = FALSE')

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f'SELECT COUNT(*) AS n FROM lookups l {where}', params)
            total = cur.fetchone()['n']

            cur.execute(
                f"""
                SELECT
                    l.id,
                    l.query,
                    l.searched_at,
                    l.success,
                    l.error_message,
                    c.nws_city,
                    c.nws_state,
                    c.display_name,
                    wr.current_temp,
                    wr.current_unit,
                    wr.current_forecast
                FROM lookups l
                LEFT JOIN cities c ON l.city_id = c.id
                LEFT JOIN weather_results wr ON l.weather_result_id = wr.id
                {where}
                ORDER BY l.searched_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            rows = [dict(row) for row in cur.fetchall()]

    return rows, total


def get_lookup_stats():
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                              AS total,
                    COUNT(*) FILTER (WHERE success)                      AS successful,
                    COUNT(DISTINCT city_id) FILTER (WHERE city_id IS NOT NULL) AS unique_cities
                FROM lookups
                """
            )
            return dict(cur.fetchone())
