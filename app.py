from flask import Flask, jsonify, render_template, request
import requests
from datetime import datetime
import db

app = Flask(__name__)
app.json.sort_keys = False

try:
    db.init_db()
except Exception as _e:
    app.logger.warning('DB init failed: %s', _e)

NWS_HEADERS = {
    'User-Agent': 'WeatherApp/1.0 (weather-flask-app)',
    'Accept': 'application/geo+json',
}


def geocode(city):
    resp = requests.get(
        'https://nominatim.openstreetmap.org/search',
        params={'q': city, 'format': 'json', 'limit': 1},
        headers={'User-Agent': NWS_HEADERS['User-Agent']},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None, None, None
    r = results[0]
    return float(r['lat']), float(r['lon']), r['display_name']


def fetch_weather(lat, lon):
    points = requests.get(
        f'https://api.weather.gov/points/{lat:.4f},{lon:.4f}',
        headers=NWS_HEADERS,
        timeout=10,
    )
    points.raise_for_status()
    props = points.json()['properties']

    forecast_r = requests.get(props['forecast'], headers=NWS_HEADERS, timeout=10)
    forecast_r.raise_for_status()
    periods = forecast_r.json()['properties']['periods']

    hourly_r = requests.get(props['forecastHourly'], headers=NWS_HEADERS, timeout=10)
    hourly_r.raise_for_status()
    hourly = hourly_r.json()['properties']['periods'][:12]

    for p in hourly:
        dt = datetime.fromisoformat(p['startTime'])
        p['hour'] = dt.strftime('%I %p').lstrip('0')
        p['precip'] = (p.get('probabilityOfPrecipitation') or {}).get('value')

    for p in periods:
        p['precip'] = (p.get('probabilityOfPrecipitation') or {}).get('value')

    loc = props.get('relativeLocation', {}).get('properties', {})
    return {
        'city': loc.get('city', ''),
        'state': loc.get('state', ''),
        'current': periods[0],
        'periods': periods,
        'hourly': hourly,
    }


def _serialize(rows):
    result = []
    for row in rows:
        r = dict(row)
        if isinstance(r.get('searched_at'), datetime):
            r['searched_at'] = r['searched_at'].isoformat()
        result.append(r)
    return result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/history')
def history_page():
    return render_template('history.html')


@app.route('/api/weather')
def api_weather():
    city_q = request.args.get('city', '').strip()
    if not city_q:
        return jsonify({'error': 'City is required'}), 400
    try:
        lat, lon, display_name = geocode(city_q)
        if lat is None:
            error = f'Location not found: "{city_q}"'
            try:
                db.save_lookup(city_q, success=False, error_message=error)
            except Exception as e:
                app.logger.warning('DB write failed: %s', e)
            return jsonify({'error': error}), 404
        weather = fetch_weather(lat, lon)
        weather['display_name'] = display_name
        try:
            city_id = db.upsert_city(display_name, lat, lon, weather['city'], weather['state'])
            wr_id = db.save_weather_result(city_id, weather)
            db.save_lookup(city_q, city_id=city_id, weather_result_id=wr_id, success=True)
        except Exception as e:
            app.logger.warning('DB write failed: %s', e)
        return jsonify({'weather': weather})
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        error = ('No weather data found — api.weather.gov only covers US locations.'
                 if code == 404 else f'Weather API error (HTTP {code}). Please try again.')
        try:
            db.save_lookup(city_q, success=False, error_message=error)
        except Exception as dbe:
            app.logger.warning('DB write failed: %s', dbe)
        return jsonify({'error': error}), 502
    except requests.RequestException as e:
        error = f'Network error: {e}'
        try:
            db.save_lookup(city_q, success=False, error_message=str(e))
        except Exception as dbe:
            app.logger.warning('DB write failed: %s', dbe)
        return jsonify({'error': error}), 502


@app.route('/api/recent')
def api_recent():
    try:
        return jsonify(_serialize(db.get_recent_lookups()))
    except Exception as e:
        app.logger.warning('DB read failed: %s', e)
        return jsonify([])


@app.route('/api/history')
def api_history():
    page = request.args.get('page', 1, type=int)
    query_filter = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    per_page = 50
    try:
        rows, total = db.get_lookup_history(page, per_page, query_filter, status_filter)
        stats = db.get_lookup_stats()
    except Exception as e:
        app.logger.warning('DB read failed: %s', e)
        rows, total, stats = [], 0, {'total': 0, 'successful': 0, 'unique_cities': 0}
    total_pages = max(1, (total + per_page - 1) // per_page)
    return jsonify({
        'rows': _serialize(rows),
        'total': total,
        'stats': stats,
        'page': page,
        'total_pages': total_pages,
        'per_page': per_page,
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
