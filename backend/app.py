"""
app.py – Luxury Travel Map Generator backend.

POST /api/generate   { cities, country, bounds? }  → JPEG
POST /api/geocode    { cities }                     → [{name, lat, lon}]
GET  /api/cities                                    → [city names]
GET  /api/regions                                   → {regions, aliases}
"""

import traceback
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

from map_generator import (generate_map, geocode_city, CITY_COORDS, REGIONS,
                           COUNTRY_ALIASES, add_custom_city,
                           get_custom_cities, delete_custom_city)

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)


# ── Frontend ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ── Map generation ─────────────────────────────────────────────────────────────

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON body.'}), 400

    cities  = data.get('cities', [])
    country = data.get('country', '').strip()
    bounds  = data.get('bounds')   # optional {north, south, east, west}

    if not isinstance(cities, list) or not cities:
        return jsonify({'error': "'cities' must be a non-empty list."}), 422
    if not country:
        return jsonify({'error': "'country' must be provided."}), 422

    # Validate bounds shape if supplied
    if bounds is not None:
        required_keys = {'north', 'south', 'east', 'west'}
        if not isinstance(bounds, dict) or not required_keys.issubset(bounds):
            return jsonify({'error': f"'bounds' must contain {required_keys}."}), 422
        bounds = {k: float(bounds[k]) for k in required_keys}

    # Strip & deduplicate (preserve order)
    seen, clean_cities = set(), []
    for c in cities:
        c = str(c).strip()
        if c and c not in seen:
            seen.add(c); clean_cities.append(c)

    if not clean_cities:
        return jsonify({'error': 'No valid city names supplied.'}), 422

    try:
        jpeg_bytes = generate_map(clean_cities, country, bounds=bounds)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    except Exception:
        traceback.print_exc()
        return jsonify({'error': 'Map generation failed – check server logs.'}), 500

    return Response(jpeg_bytes, mimetype='image/jpeg')


# ── City geocoding (for Leaflet preview) ──────────────────────────────────────

@app.route('/api/geocode', methods=['POST'])
def api_geocode():
    """Return [{name, lat, lon}] for the supplied city list."""
    data = request.get_json(force=True, silent=True) or {}
    cities = data.get('cities', [])
    result = []
    for city in cities:
        city = str(city).strip()
        if not city:
            continue
        coords = geocode_city(city)
        if coords:
            result.append({'name': city, 'lat': coords[0], 'lon': coords[1]})
    return jsonify(result)


# ── Add custom city ────────────────────────────────────────────────────────────

@app.route('/api/add-city', methods=['POST'])
def api_add_city():
    """Persist a user-supplied city coordinate and update the live database."""
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'error': 'City name is required.'}), 422
    try:
        lat = float(data['lat'])
        lon = float(data['lon'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'Valid lat and lon are required.'}), 422
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({'error': 'Coordinates out of range.'}), 422
    add_custom_city(name, lat, lon)
    return jsonify({'ok': True, 'name': name, 'lat': lat, 'lon': lon})


# ── Custom city management ─────────────────────────────────────────────────────

@app.route('/api/custom-cities')
def api_list_custom_cities():
    return jsonify(get_custom_cities())

@app.route('/api/delete-city', methods=['POST'])
def api_delete_city():
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'error': 'City name is required.'}), 422
    if not delete_custom_city(name):
        return jsonify({'error': f'"{name}" not found in custom database.'}), 404
    return jsonify({'ok': True})


# ── Autocomplete helpers ────────────────────────────────────────────────────────

@app.route('/api/cities')
def api_cities():
    return jsonify(sorted(CITY_COORDS.keys()))

@app.route('/api/regions')
def api_regions():
    return jsonify({'regions': sorted(REGIONS.keys()),
                    'aliases': sorted(COUNTRY_ALIASES.keys())})


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('Starting Luxury Travel Map server on http://localhost:5000')
    app.run(debug=True, port=5000)
