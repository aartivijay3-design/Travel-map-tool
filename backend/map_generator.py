"""
map_generator.py
Generates styled luxury route maps using geopandas + matplotlib + Natural Earth data.
"""
from __future__ import annotations   # enables | union syntax on Python 3.10+

import os
import json
import math
import warnings
import urllib.request
from io import BytesIO

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import geopandas as gpd
from shapely.geometry import Point

# ─── Color palette ─────────────────────────────────────────────────────────────
PALETTE = {
    'background':       '#FFFFFF',
    'ocean':            '#EAF2F2',   # light teal wash for non-country area
    'land_fill':        '#FFFFFF',   # country interior: white
    'border':           '#6EAAA8',   # teal for country/region borders
    'route':            '#6EAAA8',   # teal route line
    'label':            '#CC8B1A',   # yellow ochre for destination labels
    'country_name':     '#CC8B1A',   # yellow ochre country name watermark
    'city_face':        '#6EAAA8',   # teal pin fill
    'city_edge':        '#FFFFFF',   # white pin outline
    'city_inner':       '#FFFFFF',   # inner dot of pin
    'deco_border':      '#C8A02A',   # gold decorative frame
    'road':             '#C8C8C8',   # light grey road lines
    'other_city':       '#AAAAAA',   # non-route city label colour
    'bg_world':         '#E4EDED',   # surrounding land (world bg)
    'bg_world_edge':    '#C8D8D8',
}

# ─── Natural Earth data ─────────────────────────────────────────────────────────
DATA_DIR          = os.path.join(os.path.dirname(__file__), 'data')
CUSTOM_CITIES_FILE = os.path.join(DATA_DIR, 'custom_cities.json')  # legacy – only used for one-time migration
_SQLITE_PATH       = os.path.join(DATA_DIR, 'custom_cities.db')
_DATABASE_URL      = os.environ.get('DATABASE_URL')  # set on Render; absent → SQLite


class _CityDB:
    """Thin wrapper that talks SQLite locally and PostgreSQL on Render."""

    def _connect(self):
        if _DATABASE_URL:
            import psycopg2
            return psycopg2.connect(_DATABASE_URL), '%s'
        return __import__('sqlite3').connect(_SQLITE_PATH), '?'

    def init(self):
        conn, _ = self._connect()
        try:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS custom_cities (
                    name TEXT PRIMARY KEY,
                    lat  REAL NOT NULL,
                    lon  REAL NOT NULL
                )
            ''')
            conn.commit()
            self._migrate_json(conn, _)
        finally:
            conn.close()

    def _migrate_json(self, conn, ph):
        """Import existing custom_cities.json once, then remove it."""
        if not os.path.exists(CUSTOM_CITIES_FILE):
            return
        try:
            with open(CUSTOM_CITIES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cur = conn.cursor()
            for name, coords in data.items():
                cur.execute(
                    f'INSERT INTO custom_cities (name,lat,lon) VALUES ({ph},{ph},{ph}) '
                    f'ON CONFLICT(name) DO NOTHING',
                    (name, float(coords[0]), float(coords[1]))
                )
            conn.commit()
            os.rename(CUSTOM_CITIES_FILE, CUSTOM_CITIES_FILE + '.migrated')
        except Exception as exc:
            print(f'Migration warning: {exc}')

    def load_all(self) -> dict:
        conn, _ = self._connect()
        try:
            cur = conn.cursor()
            cur.execute('SELECT name, lat, lon FROM custom_cities')
            return {row[0]: (float(row[1]), float(row[2])) for row in cur.fetchall()}
        except Exception:
            return {}
        finally:
            conn.close()

    def upsert(self, name: str, lat: float, lon: float):
        conn, ph = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f'INSERT INTO custom_cities (name,lat,lon) VALUES ({ph},{ph},{ph}) '
                f'ON CONFLICT(name) DO UPDATE SET lat={ph}, lon={ph}',
                (name, lat, lon, lat, lon)
            )
            conn.commit()
        except Exception as exc:
            print(f'Warning – could not persist custom city: {exc}')
        finally:
            conn.close()

    def delete(self, name: str) -> bool:
        conn, ph = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(f'DELETE FROM custom_cities WHERE name = {ph}', (name,))
            conn.commit()
            return cur.rowcount > 0
        except Exception as exc:
            print(f'Warning – could not delete custom city: {exc}')
            return False
        finally:
            conn.close()


_db = _CityDB()
_db.init()
_GH               = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/'

NE_GEOJSON = os.path.join(DATA_DIR, 'ne_110m_admin_0_countries.geojson')
NE_ADMIN1  = os.path.join(DATA_DIR, 'ne_50m_admin_1_states_provinces.geojson')
NE_PLACES  = os.path.join(DATA_DIR, 'ne_110m_populated_places_simple.geojson')

NE_URL        = _GH + 'ne_110m_admin_0_countries.geojson'
NE_ADMIN1_URL = _GH + 'ne_50m_admin_1_states_provinces.geojson'
NE_PLACES_URL = _GH + 'ne_110m_populated_places_simple.geojson'

# ─── Country name aliases ───────────────────────────────────────────────────────
COUNTRY_ALIASES = {
    'usa': 'United States of America',
    'us': 'United States of America',
    'united states': 'United States of America',
    'america': 'United States of America',
    'uk': 'United Kingdom',
    'great britain': 'United Kingdom',
    'england': 'United Kingdom',
    'uae': 'United Arab Emirates',
    'south korea': 'South Korea',
    'north korea': 'North Korea',
    'laos': 'Lao PDR',
    'czech republic': 'Czechia',
    'burma': 'Myanmar',
    'siam': 'Thailand',
    'persia': 'Iran',
    'ivory coast': "Côte d'Ivoire",
    'holland': 'Netherlands',
}

# ─── Region → country list ──────────────────────────────────────────────────────
REGIONS = {
    'southeast asia':    ['Vietnam', 'Thailand', 'Cambodia', 'Myanmar', 'Lao PDR',
                          'Malaysia', 'Indonesia', 'Philippines', 'Singapore', 'Brunei'],
    'western europe':    ['France', 'Germany', 'Italy', 'Spain', 'Switzerland', 'Austria',
                          'Belgium', 'Netherlands', 'Portugal', 'Luxembourg'],
    'middle east':       ['Turkey', 'Jordan', 'Israel', 'Lebanon', 'Egypt',
                          'United Arab Emirates', 'Saudi Arabia', 'Oman', 'Qatar'],
    'south asia':        ['India', 'Nepal', 'Sri Lanka', 'Bhutan', 'Pakistan', 'Bangladesh'],
    'east asia':         ['China', 'Japan', 'South Korea'],
    'north africa':      ['Morocco', 'Tunisia', 'Egypt', 'Algeria', 'Libya'],
    'east africa':       ['Kenya', 'Tanzania', 'Uganda', 'Rwanda', 'Ethiopia', 'Mozambique'],
    'southern africa':   ['South Africa', 'Zimbabwe', 'Botswana', 'Namibia', 'Zambia'],
    'scandinavia':       ['Norway', 'Sweden', 'Denmark', 'Finland'],
    'balkans':           ['Greece', 'Croatia', 'Montenegro', 'Albania',
                          'North Macedonia', 'Bosnia and Herz.', 'Serbia'],
    'british isles':     ['United Kingdom', 'Ireland'],
    'iberian peninsula': ['Spain', 'Portugal'],
    'central america':   ['Mexico', 'Guatemala', 'Belize', 'Honduras',
                          'El Salvador', 'Nicaragua', 'Costa Rica', 'Panama'],
    'caribbean':         ['Cuba', 'Dominican Rep.', 'Haiti', 'Jamaica'],
    'andean':            ['Peru', 'Bolivia', 'Ecuador', 'Colombia'],
    'southern cone':     ['Argentina', 'Chile', 'Uruguay', 'Paraguay'],
    'central asia':      ['Kazakhstan', 'Uzbekistan', 'Kyrgyzstan', 'Tajikistan', 'Turkmenistan'],
    'caucasus':          ['Georgia', 'Armenia', 'Azerbaijan'],
    'north america':     ['United States of America', 'Canada', 'Mexico'],
    'europe':            ['France', 'Germany', 'Italy', 'Spain', 'Switzerland', 'Austria',
                          'Belgium', 'Netherlands', 'Portugal', 'Poland', 'Czechia',
                          'Hungary', 'Romania', 'Greece', 'Croatia', 'Norway', 'Sweden',
                          'Denmark', 'Finland', 'United Kingdom', 'Ireland'],
}

# ─── City coordinate database ──────────────────────────────────────────────────
CITY_COORDS = {
    # China
    'Beijing':       (39.9042, 116.4074),
    "Xi'an":         (34.3416, 108.9398),
    'Xian':          (34.3416, 108.9398),
    'Shanghai':      (31.2304, 121.4737),
    'Guilin':        (25.2736, 110.2900),
    'Chengdu':       (30.5728, 104.0668),
    'Lhasa':         (29.6520,  91.1720),
    'Lijiang':       (26.8720, 100.2300),
    'Zhangjiajie':   (29.1248, 110.4792),
    'Hangzhou':      (30.2741, 120.1551),
    'Suzhou':        (31.2990, 120.5853),
    'Chongqing':     (29.5630, 106.5516),
    'Kunming':       (25.0456, 102.7097),
    'Guangzhou':     (23.1291, 113.2644),
    'Hong Kong':     (22.3193, 114.1694),
    'Macau':         (22.1987, 113.5439),
    'Shenzhen':      (22.5431, 114.0579),
    'Wuhan':         (30.5928, 114.3055),
    'Nanjing':       (32.0603, 118.7969),
    'Qingdao':       (36.0671, 120.3826),
    'Sanya':         (18.2524, 109.5119),
    'Dunhuang':      (40.1428,  94.6620),
    'Urumqi':        (43.8256,  87.6168),
    'Harbin':        (45.8038, 126.5340),
    'Pingyao':       (37.1897, 112.1762),
    'Zhengzhou':     (34.7472, 113.6249),
    # Japan
    'Tokyo':         (35.6762, 139.6503),
    'Kyoto':         (35.0116, 135.7681),
    'Osaka':         (34.6937, 135.5023),
    'Hiroshima':     (34.3853, 132.4553),
    'Nara':          (34.6851, 135.8048),
    'Hakone':        (35.2326, 139.1069),
    'Nikko':         (36.7198, 139.6983),
    'Sapporo':       (43.0618, 141.3545),
    'Fukuoka':       (33.5904, 130.4017),
    'Nagasaki':      (32.7503, 129.8777),
    'Kanazawa':      (36.5613, 136.6562),
    'Nagoya':        (35.1815, 136.9066),
    'Kamakura':      (35.3192, 139.5469),
    'Takayama':      (36.1408, 137.2519),
    # South Korea
    'Seoul':         (37.5665, 126.9780),
    'Busan':         (35.1796, 129.0756),
    'Gyeongju':      (35.8562, 129.2247),
    'Jeju':          (33.4996, 126.5312),
    # Thailand
    'Bangkok':       (13.7563, 100.5018),
    'Chiang Mai':    (18.7883,  98.9853),
    'Phuket':        ( 7.8804,  98.3923),
    'Ayutthaya':     (14.3531, 100.5671),
    'Krabi':         ( 8.0863,  98.9063),
    'Koh Samui':     ( 9.5120, 100.0136),
    'Sukhothai':     (17.0166,  99.8231),
    # Vietnam
    'Hanoi':         (21.0278, 105.8342),
    'Ho Chi Minh City': (10.8231, 106.6297),
    'Saigon':        (10.8231, 106.6297),
    'Hoi An':        (15.8801, 108.3380),
    'Hue':           (16.4637, 107.5909),
    'Ha Long':       (20.9517, 107.0740),
    'Halong Bay':    (20.9517, 107.0740),
    'Nha Trang':     (12.2388, 109.1967),
    'Da Nang':       (16.0544, 108.2022),
    'Sapa':          (22.3364, 103.8438),
    # Cambodia
    'Phnom Penh':    (11.5564, 104.9282),
    'Siem Reap':     (13.3633, 103.8564),
    'Battambang':    (13.0957, 103.2022),
    # Myanmar
    'Yangon':        (16.8661,  96.1951),
    'Mandalay':      (21.9750,  96.0833),
    'Bagan':         (21.1717,  94.8585),
    'Inle Lake':     (20.5303,  96.9012),
    # Laos
    'Vientiane':     (17.9757, 102.6331),
    'Luang Prabang': (19.8931, 102.1368),
    # Indonesia
    'Bali':          (-8.3405, 115.0920),
    'Ubud':          (-8.5069, 115.2625),
    'Jakarta':       (-6.2088, 106.8456),
    'Yogyakarta':    (-7.7956, 110.3695),
    'Komodo':        (-8.5700, 119.4880),
    # Philippines
    'Manila':        (14.5995, 120.9842),
    'Cebu':          (10.3157, 123.8854),
    'Palawan':       ( 9.8349, 118.7384),
    # Malaysia
    'Kuala Lumpur':  ( 3.1390, 101.6869),
    'Penang':        ( 5.4164, 100.3327),
    'Langkawi':      ( 6.3500,  99.8000),
    # Singapore
    'Singapore':     ( 1.3521, 103.8198),
    # India – major cities
    'Mumbai':        (19.0760,  72.8777),
    'Delhi':         (28.6139,  77.2090),
    'New Delhi':     (28.6139,  77.2090),
    'Agra':          (27.1767,  78.0081),
    'Jaipur':        (26.9124,  75.7873),
    'Udaipur':       (24.5854,  73.7125),
    'Varanasi':      (25.3176,  82.9739),
    'Kolkata':       (22.5726,  88.3639),
    'Chennai':       (13.0827,  80.2707),
    'Goa':           (15.2993,  74.1240),
    'Rishikesh':     (30.0869,  78.2676),
    'Amritsar':      (31.6340,  74.8723),
    'Bangalore':     (12.9716,  77.5946),
    'Bengaluru':     (12.9716,  77.5946),
    'Hyderabad':     (17.3850,  78.4867),
    'Mysore':        (12.2958,  76.6394),
    'Mysuru':        (12.2958,  76.6394),
    'Jodhpur':       (26.2389,  73.0243),
    'Pushkar':       (26.4899,  74.5511),
    'Hampi':         (15.3350,  76.4600),
    'Kochi':         ( 9.9312,  76.2673),
    'Cochin':        ( 9.9312,  76.2673),
    'Darjeeling':    (27.0360,  88.2627),
    'Shimla':        (31.1048,  77.1734),
    # India – Rajasthan & North
    'Jaisalmer':     (26.9157,  70.9083),
    'Bikaner':       (28.0229,  73.3119),
    'Ajmer':         (26.4499,  74.6399),
    'Mount Abu':     (24.5926,  72.7156),
    'Ranthambore':   (26.0173,  76.5026),
    'Bharatpur':     (27.2152,  77.5030),
    'Alwar':         (27.5530,  76.6346),
    'Bundi':         (25.4409,  75.6399),
    'Kota':          (25.2138,  75.8648),
    'Chittorgarh':   (24.8887,  74.6269),
    # India – North / Himalaya
    'Leh':           (34.1526,  77.5771),
    'Ladakh':        (34.1526,  77.5771),
    'Srinagar':      (34.0837,  74.7973),
    'Gulmarg':       (34.0484,  74.3805),
    'Pahalgam':      (34.0161,  75.3150),
    'Manali':        (32.2432,  77.1892),
    'Mussoorie':     (30.4598,  78.0644),
    'Nainital':      (29.3803,  79.4636),
    'Haridwar':      (29.9457,  78.1642),
    'Dehradun':      (30.3165,  78.0322),
    'Jim Corbett':   (29.5300,  78.7747),
    'Corbett':       (29.5300,  78.7747),
    'Kasauli':       (30.9011,  76.9661),
    'McLeod Ganj':   (32.2394,  76.3234),
    'Dharamsala':    (32.2190,  76.3234),
    'Spiti':         (32.2647,  78.0338),
    'Kalpa':         (31.5325,  78.2588),
    # India – South
    'Pondicherry':   (11.9416,  79.8083),
    'Puducherry':    (11.9416,  79.8083),
    'Madurai':       ( 9.9252,  78.1198),
    'Thanjavur':     (10.7870,  79.1378),
    'Tanjore':       (10.7870,  79.1378),
    'Ooty':          (11.4102,  76.6950),
    'Udhagamandalam':(11.4102,  76.6950),
    'Munnar':        (10.0889,  77.0595),
    'Alleppey':      ( 9.4981,  76.3388),
    'Alappuzha':     ( 9.4981,  76.3388),
    'Thekkady':      ( 9.5944,  77.1698),
    'Periyar':       ( 9.5944,  77.1698),
    'Kovalam':       ( 8.3988,  76.9782),
    'Varkala':       ( 8.7379,  76.7163),
    'Trivandrum':    ( 8.5241,  76.9366),
    'Thiruvananthapuram': ( 8.5241, 76.9366),
    'Rameswaram':    ( 9.2876,  79.3129),
    'Kanyakumari':   ( 8.0883,  77.5385),
    'Mahabalipuram': (12.6269,  80.1927),
    'Mamallapuram':  (12.6269,  80.1927),
    'Coorg':         (12.3375,  75.8069),
    'Kodagu':        (12.3375,  75.8069),
    'Badami':        (15.9179,  75.6767),
    'Aihole':        (16.0192,  75.8835),
    'Pattadakal':    (15.9482,  75.8172),
    'Belur':         (13.1648,  75.8600),
    'Halebidu':      (13.2127,  75.9945),
    'Halebid':       (13.2127,  75.9945),
    # India – Central & East
    'Khajuraho':     (24.8318,  79.9199),
    'Bhopal':        (23.2599,  77.4126),
    'Indore':        (22.7196,  75.8577),
    'Ahmedabad':     (23.0225,  72.5714),
    'Surat':         (21.1702,  72.8311),
    'Nashik':        (19.9975,  73.7898),
    'Aurangabad':    (19.8762,  75.3433),
    'Ajanta':        (20.5524,  75.7033),
    'Ellora':        (20.0268,  75.1794),
    'Pune':          (18.5204,  73.8567),
    'Prayagraj':     (25.4358,  81.8463),
    'Allahabad':     (25.4358,  81.8463),
    'Lucknow':       (26.8467,  80.9462),
    'Orchha':        (25.3519,  78.6417),
    'Gwalior':       (26.2183,  78.1828),
    'Sanchi':        (23.4793,  77.7373),
    # India – Northeast
    'Shillong':      (25.5788,  91.8933),
    'Kaziranga':     (26.5775,  93.1710),
    'Guwahati':      (26.1445,  91.7362),
    'Gangtok':       (27.3389,  88.6065),
    'Pelling':       (27.2906,  88.1073),
    'Tawang':        (27.5861,  91.8594),
    'Ziro':          (27.5485,  93.8302),
    # Nepal
    'Kathmandu':     (27.7172,  85.3240),
    'Pokhara':       (28.2096,  83.9856),
    'Chitwan':       (27.5291,  84.3542),
    # Sri Lanka
    'Colombo':       ( 6.9271,  79.8612),
    'Kandy':         ( 7.2906,  80.6337),
    'Sigiriya':      ( 7.9570,  80.7603),
    'Galle':         ( 6.0535,  80.2210),
    # UAE
    'Dubai':         (25.2048,  55.2708),
    'Abu Dhabi':     (24.4539,  54.3773),
    # Jordan
    'Amman':         (31.9454,  35.9284),
    'Petra':         (30.3285,  35.4444),
    'Aqaba':         (29.5321,  35.0063),
    'Wadi Rum':      (29.5758,  35.4229),
    # Egypt
    'Cairo':         (30.0444,  31.2357),
    'Luxor':         (25.6872,  32.6396),
    'Aswan':         (24.0889,  32.8998),
    'Hurghada':      (27.2579,  33.8116),
    'Alexandria':    (31.2001,  29.9187),
    # Morocco
    'Marrakech':     (31.6295,  -7.9811),
    'Fez':           (34.0181,  -5.0078),
    'Casablanca':    (33.5731,  -7.5898),
    'Rabat':         (34.0209,  -6.8416),
    'Chefchaouen':   (35.1714,  -5.2636),
    'Essaouira':     (31.5085,  -9.7595),
    'Merzouga':      (31.0997,  -4.0138),
    # Turkey
    'Istanbul':      (41.0082,  28.9784),
    'Cappadocia':    (38.6431,  34.8289),
    'Pamukkale':     (37.9204,  29.1188),
    'Antalya':       (36.8969,  30.7133),
    'Bodrum':        (37.0344,  27.4305),
    'Ankara':        (39.9334,  32.8597),
    'Trabzon':       (41.0015,  39.7178),
    # Greece
    'Athens':        (37.9838,  23.7275),
    'Santorini':     (36.3932,  25.4615),
    'Mykonos':       (37.4445,  25.3289),
    'Rhodes':        (36.4341,  28.2176),
    'Thessaloniki':  (40.6401,  22.9444),
    'Crete':         (35.2401,  24.8093),
    'Corfu':         (39.6243,  19.9217),
    'Meteora':       (39.7217,  21.6306),
    # Italy
    'Rome':          (41.9028,  12.4964),
    'Venice':        (45.4408,  12.3155),
    'Florence':      (43.7696,  11.2558),
    'Milan':         (45.4654,   9.1859),
    'Naples':        (40.8518,  14.2681),
    'Amalfi':        (40.6340,  14.6024),
    'Positano':      (40.6281,  14.4849),
    'Cinque Terre':  (44.1270,   9.7063),
    'Palermo':       (38.1157,  13.3615),
    'Bologna':       (44.4949,  11.3426),
    'Pisa':          (43.7228,  10.4017),
    'Siena':         (43.3186,  11.3307),
    'Turin':         (45.0703,   7.6869),
    'Verona':        (45.4384,  10.9916),
    'Capri':         (40.5500,  14.2422),
    # France
    'Paris':         (48.8566,   2.3522),
    'Lyon':          (45.7640,   4.8357),
    'Marseille':     (43.2965,   5.3698),
    'Nice':          (43.7102,   7.2620),
    'Bordeaux':      (44.8378,  -0.5792),
    'Strasbourg':    (48.5734,   7.7521),
    'Avignon':       (43.9493,   4.8055),
    'Cannes':        (43.5528,   7.0174),
    'Monaco':        (43.7384,   7.4246),
    'Versailles':    (48.8049,   2.1204),
    # Spain
    'Madrid':        (40.4168,  -3.7038),
    'Barcelona':     (41.3851,   2.1734),
    'Seville':       (37.3891,  -5.9845),
    'Granada':       (37.1773,  -3.5986),
    'Valencia':      (39.4699,  -0.3763),
    'Bilbao':        (43.2630,  -2.9350),
    'Toledo':        (39.8628,  -4.0273),
    'Cordoba':       (37.8882,  -4.7794),
    'Malaga':        (36.7213,  -4.4214),
    # Portugal
    'Lisbon':        (38.7223,  -9.1393),
    'Porto':         (41.1579,  -8.6291),
    'Sintra':        (38.7978,  -9.3877),
    # United Kingdom
    'London':        (51.5074,  -0.1278),
    'Edinburgh':     (55.9533,  -3.1883),
    'Oxford':        (51.7520,  -1.2577),
    'Cambridge':     (52.2053,   0.1218),
    'Bath':          (51.3758,  -2.3599),
    'York':          (53.9600,  -1.0873),
    'Stonehenge':    (51.1789,  -1.8262),
    # Germany
    'Berlin':        (52.5200,  13.4050),
    'Munich':        (48.1351,  11.5820),
    'Hamburg':       (53.5511,   9.9937),
    'Cologne':       (50.9333,   6.9500),
    'Frankfurt':     (50.1109,   8.6821),
    'Heidelberg':    (49.3988,   8.6724),
    'Rothenburg':    (49.3776,  10.1777),
    'Neuschwanstein':(47.5576,  10.7498),
    'Dresden':       (51.0504,  13.7373),
    'Nuremberg':     (49.4521,  11.0767),
    # Austria
    'Vienna':        (48.2082,  16.3738),
    'Salzburg':      (47.8095,  13.0550),
    'Innsbruck':     (47.2692,  11.4041),
    'Hallstatt':     (47.5622,  13.6493),
    # Switzerland
    'Zurich':        (47.3769,   8.5417),
    'Geneva':        (46.2044,   6.1432),
    'Bern':          (46.9481,   7.4474),
    'Lucerne':       (47.0502,   8.3093),
    'Interlaken':    (46.6863,   7.8632),
    'Zermatt':       (46.0207,   7.7491),
    # Czech Republic / Czechia
    'Prague':        (50.0755,  14.4378),
    'Cesky Krumlov': (48.8127,  14.3175),
    # Hungary
    'Budapest':      (47.4979,  19.0402),
    # Poland
    'Warsaw':        (52.2297,  21.0122),
    'Krakow':        (50.0647,  19.9450),
    'Gdansk':        (54.3520,  18.4661),
    # Netherlands
    'Amsterdam':     (52.3676,   4.9041),
    'Rotterdam':     (51.9244,   4.4777),
    # Belgium
    'Brussels':      (50.8503,   4.3517),
    'Bruges':        (51.2093,   3.2247),
    'Ghent':         (51.0543,   3.7174),
    # Scandinavia
    'Stockholm':     (59.3293,  18.0686),
    'Oslo':          (59.9139,  10.7522),
    'Copenhagen':    (55.6761,  12.5683),
    'Helsinki':      (60.1699,  24.9384),
    'Bergen':        (60.3913,   5.3221),
    'Tromsø':        (69.6489,  18.9551),
    'Tromso':        (69.6489,  18.9551),
    # Iceland
    'Reykjavik':     (64.1355, -21.8954),
    # Russia
    'Moscow':        (55.7558,  37.6173),
    'St. Petersburg':(59.9343,  30.3351),
    'Saint Petersburg': (59.9343, 30.3351),
    # Croatia
    'Zagreb':        (45.8150,  15.9819),
    'Dubrovnik':     (42.6507,  18.0944),
    'Split':         (43.5081,  16.4402),
    'Hvar':          (43.1724,  16.4411),
    # Israel / Palestine
    'Jerusalem':     (31.7683,  35.2137),
    'Tel Aviv':      (32.0853,  34.7818),
    # USA
    'New York':      (40.7128, -74.0060),
    'Los Angeles':   (34.0522,-118.2437),
    'Las Vegas':     (36.1699,-115.1398),
    'San Francisco': (37.7749,-122.4194),
    'Chicago':       (41.8781, -87.6298),
    'New Orleans':   (29.9511, -90.0715),
    'Miami':         (25.7617, -80.1918),
    'Washington DC': (38.9072, -77.0369),
    'Nashville':     (36.1627, -86.7816),
    'Seattle':       (47.6062,-122.3321),
    'Denver':        (39.7392,-104.9903),
    'Boston':        (42.3601, -71.0589),
    'Atlanta':       (33.7490, -84.3880),
    'Houston':       (29.7604, -95.3698),
    'Austin':        (30.2672, -97.7431),
    'Grand Canyon':  (36.1069,-112.1129),
    'Yellowstone':   (44.4280,-110.5885),
    'Yosemite':      (37.8651,-119.5383),
    # Canada
    'Toronto':       (43.6532, -79.3832),
    'Vancouver':     (49.2827,-123.1207),
    'Montreal':      (45.5017, -73.5673),
    'Quebec City':   (46.8139, -71.2080),
    'Banff':         (51.1784,-115.5708),
    # Mexico
    'Mexico City':   (19.4326, -99.1332),
    'Cancun':        (21.1619, -86.8515),
    'Oaxaca':        (17.0732, -96.7266),
    'Tulum':         (20.2114, -87.4654),
    'Chichen Itza':  (20.6843, -88.5678),
    # Brazil
    'Rio de Janeiro':(-22.9068, -43.1729),
    'Sao Paulo':     (-23.5505, -46.6333),
    'Iguazu Falls':  (-25.6953, -54.4367),
    # Argentina
    'Buenos Aires':  (-34.6037, -58.3816),
    'Mendoza':       (-32.8895, -68.8458),
    'Bariloche':     (-41.1335, -71.3103),
    'Ushuaia':       (-54.8019, -68.3030),
    # Peru
    'Lima':          (-12.0464, -77.0428),
    'Machu Picchu':  (-13.1631, -72.5450),
    'Cusco':         (-13.5319, -71.9675),
    'Arequipa':      (-16.4090, -71.5375),
    # Chile
    'Santiago':      (-33.4489, -70.6693),
    'Valparaiso':    (-33.0472, -71.6127),
    # Colombia
    'Bogota':        (  4.7110, -74.0721),
    'Cartagena':     ( 10.3910, -75.4794),
    'Medellin':      (  6.2442, -75.5812),
    # South Africa
    'Cape Town':     (-33.9249,  18.4241),
    'Johannesburg':  (-26.2041,  28.0473),
    'Durban':        (-29.8587,  31.0218),
    # Kenya
    'Nairobi':       ( -1.2921,  36.8219),
    'Mombasa':       ( -4.0435,  39.6682),
    'Maasai Mara':   ( -1.5167,  35.1500),
    'Masai Mara':    ( -1.5167,  35.1500),
    # Tanzania
    'Dar es Salaam': ( -6.7924,  39.2083),
    'Zanzibar':      ( -6.1659,  39.2026),
    'Arusha':        ( -3.3869,  36.6830),
    'Serengeti':     ( -2.3333,  34.8333),
    # Ethiopia
    'Addis Ababa':   (  9.0320,  38.7469),
    'Lalibela':      ( 12.0310,  39.0479),
    # Australia
    'Sydney':        (-33.8688, 151.2093),
    'Melbourne':     (-37.8136, 144.9631),
    'Brisbane':      (-27.4698, 153.0251),
    'Perth':         (-31.9505, 115.8605),
    'Adelaide':      (-34.9285, 138.6007),
    'Cairns':        (-16.9186, 145.7781),
    'Uluru':         (-25.3444, 131.0369),
    'Gold Coast':    (-28.0167, 153.4000),
    # New Zealand
    'Auckland':      (-36.8485, 174.7633),
    'Wellington':    (-41.2865, 174.7762),
    'Queenstown':    (-45.0312, 168.6626),
    'Christchurch':  (-43.5321, 172.6362),
    'Rotorua':       (-38.1368, 176.2497),
    # Maldives
    'Male':          (  4.1755,  73.5093),
    # Bhutan
    'Thimphu':       ( 27.4661,  89.6419),
    'Paro':          ( 27.4294,  89.4156),
    'Punakha':       ( 27.5816,  89.8677),

    # ── Italy – extra ──────────────────────────────────────────────────────────
    'Lake Como':     (45.9946,   9.2571),
    'Como':          (45.8080,   9.0852),
    'Lake Garda':    (45.6389,  10.6552),
    'Portofino':     (44.3034,   9.2096),
    'Matera':        (40.6664,  16.6043),
    'Lecce':         (40.3516,  18.1750),
    'Bari':          (41.1171,  16.8719),
    'Alghero':       (40.5586,   8.3201),
    'Asti':          (44.9003,   8.2064),
    'Ravenna':       (44.4184,  12.2035),
    'Tivoli':        (41.9634,  12.7981),
    'Orvieto':       (42.7185,  12.1112),
    'Assisi':        (43.0707,  12.6193),
    'Perugia':       (43.1107,  12.3908),
    'Trento':        (46.0748,  11.1217),
    'Trieste':       (45.6495,  13.7768),

    # ── France – extra ─────────────────────────────────────────────────────────
    'Provence':      (43.8350,   5.7320),
    'Normandy':      (49.1829,   0.3707),
    'Alsace':        (48.3181,   7.4416),
    'Loire Valley':  (47.3900,   0.6880),
    'Dordogne':      (44.8820,   0.5469),
    'Brittany':      (48.2141,  -2.9326),
    'Mont Saint-Michel': (48.6361, -1.5115),
    'Chamonix':      (45.9237,   6.8694),
    'Annecy':        (45.8992,   6.1294),
    'Colmar':        (48.0793,   7.3585),
    'Carcassonne':   (43.2130,   2.3491),
    'Montpellier':   (43.6108,   3.8767),
    'Aix-en-Provence':(43.5297,  5.4474),
    'Toulouse':      (43.6047,   1.4442),
    'Biarritz':      (43.4832,  -1.5586),
    'Champagne':     (49.0440,   4.0240),

    # ── Spain – extra ──────────────────────────────────────────────────────────
    'Andalusia':     (37.5443,  -4.7278),
    'Costa Brava':   (41.9835,   3.2094),
    'Mallorca':      (39.6953,   3.0176),
    'Palma':         (39.5696,   2.6502),
    'Ibiza':         (38.9067,   1.4206),
    'San Sebastian': (43.3183,  -1.9812),
    'Bilbao':        (43.2630,  -2.9350),
    'Pamplona':      (42.8125,  -1.6458),
    'Segovia':       (40.9429,  -4.1088),
    'Salamanca':     (40.9701,  -5.6635),
    'Tarragona':     (41.1189,   1.2445),
    'Zaragoza':      (41.6561,  -0.8773),
    'Alicante':      (38.3452,  -0.4810),

    # ── Portugal – extra ───────────────────────────────────────────────────────
    'Algarve':       (37.0179,  -8.1303),
    'Faro':          (37.0194,  -7.9322),
    'Lagos':         (37.1020,  -8.6735),
    'Douro Valley':  (41.1636,  -7.7861),
    'Evora':         (38.5741,  -7.9059),
    'Obidos':        (39.3622,  -9.1568),
    'Nazare':        (39.6038,  -9.0717),
    'Coimbra':       (40.2033,  -8.4103),
    'Braga':         (41.5454,  -8.4265),
    'Viana do Castelo': (41.6946, -8.8307),
    'Madeira':       (32.7607, -16.9595),
    'Funchal':       (32.6669, -16.9241),
    'Azores':        (37.7412, -25.6756),

    # ── United Kingdom – extra ─────────────────────────────────────────────────
    'Cotswolds':     (51.8333,  -1.7500),
    'Cornwall':      (50.2660,  -5.0527),
    'Lake District': (54.4609,  -3.0886),
    'Scottish Highlands': (57.1200, -4.7100),
    'Inverness':     (57.4778,  -4.2247),
    'St Andrews':    (56.3398,  -2.7967),
    'Windsor':       (51.4839,  -0.6044),
    'Canterbury':    (51.2802,   1.0789),
    'Stratford-upon-Avon': (52.1916, -1.7083),
    'Cardiff':       (51.4816,  -3.1791),
    'Dublin':        (53.3498,  -6.2603),
    'Galway':        (53.2707,  -9.0568),
    'Killarney':     (52.0599,  -9.5044),
    'Belfast':       (54.5973,  -5.9301),

    # ── Germany – extra ────────────────────────────────────────────────────────
    'Black Forest':  (47.9990,   8.1250),
    'Bavaria':       (48.7904,  11.4979),
    'Rhine Valley':  (50.1109,   7.6789),
    'Bamberg':       (49.8988,  10.9028),
    'Regensburg':    (49.0134,  12.1016),
    'Freiburg':      (47.9990,   7.8421),
    'Stuttgart':     (48.7758,   9.1829),
    'Dusseldorf':    (51.2217,   6.7762),
    'Leipzig':       (51.3397,  12.3731),
    'Lubeck':        (53.8655,  10.6866),

    # ── Greece – extra ─────────────────────────────────────────────────────────
    'Delphi':        (38.4824,  22.5010),
    'Olympia':       (37.6379,  21.6300),
    'Epidaurus':     (37.5952,  23.0775),
    'Nafplio':       (37.5677,  22.8019),
    'Zakynthos':     (37.7902,  20.9046),
    'Kefalonia':     (38.1753,  20.5694),
    'Patmos':        (37.3229,  26.5463),
    'Chania':        (35.5138,  24.0180),
    'Heraklion':     (35.3387,  25.1442),

    # ── Balkans & Eastern Europe ───────────────────────────────────────────────
    'Plitvice':      (44.8654,  15.5820),
    'Kotor':         (42.4247,  18.7712),
    'Montenegro':    (42.7087,  19.3744),
    'Mostar':        (43.3438,  17.8078),
    'Sarajevo':      (43.8563,  18.4131),
    'Ljubljana':     (46.0569,  14.5058),
    'Bled':          (46.3683,  14.1146),
    'Ohrid':         (41.1231,  20.8016),
    'Tirana':        (41.3275,  19.8187),
    'Plovdiv':       (42.1354,  24.7453),
    'Sofia':         (42.6977,  23.3219),
    'Bucharest':     (44.4268,  26.1025),
    'Brasov':        (45.6427,  25.5887),
    'Sinaia':        (45.3524,  25.5504),
    'Tallinn':       (59.4370,  24.7536),
    'Riga':          (56.9460,  24.1059),
    'Vilnius':       (54.6872,  25.2797),

    # ── Mediterranean islands ──────────────────────────────────────────────────
    'Malta':         (35.9375,  14.3754),
    'Valletta':      (35.8997,  14.5147),
    'Sicily':        (37.5999,  14.0154),
    'Sardinia':      (40.1209,   9.0129),
    'Cyprus':        (35.1264,  33.4299),
    'Nicosia':       (35.1856,  33.3823),

    # ── Middle East – extra ────────────────────────────────────────────────────
    'Muscat':        (23.5880,  58.3829),
    'Nizwa':         (22.9333,  57.5333),
    'Salalah':       (17.0151,  54.0924),
    'Riyadh':        (24.6877,  46.7219),
    'Jeddah':        (21.4858,  39.1925),
    'Medina':        (24.5247,  39.5692),
    'Kuwait City':   (29.3759,  47.9774),
    'Doha':          (25.2854,  51.5310),
    'Manama':        (26.2154,  50.5832),
    'Beirut':        (33.8938,  35.5018),
    'Damascus':      (33.5138,  36.2765),
    'Oman':          (23.5880,  58.3829),

    # ── Africa – extra ─────────────────────────────────────────────────────────
    'Stellenbosch':  (-33.9321,  18.8602),
    'Kruger':        (-23.9884,  31.5549),
    'Garden Route':  (-33.9891,  22.4575),
    'George':        (-33.9644,  22.4609),
    'Knysna':        (-34.0361,  23.0465),
    'Victoria Falls':(-17.9243,  25.8567),
    'Chobe':         (-18.8300,  24.7100),
    'Okavango':      (-19.2833,  22.9167),
    'Marrakech':     (31.6295,  -7.9811),    # already listed above but keep alias
    'Luxor':         (25.6872,  32.6396),
    'Sharm El Sheikh':(27.9158,  34.3300),
    'Hurghada':      (27.2579,  33.8116),
    'Amboseli':      (-2.6527,  37.2530),
    'Tsavo':         (-2.8600,  38.2500),
    'Samburu':       ( 0.5740,  37.5340),
    'Diani Beach':   (-4.3128,  39.5721),
    'Kigali':        (-1.9441,  30.0619),
    'Accra':         ( 5.6037,  -0.1870),
    'Lagos':         ( 6.5244,   3.3792),
    'Abuja':         ( 9.0765,   7.3986),
    'Dakar':         (14.7167,  -17.4677),
    'Casablanca':    (33.5731,  -7.5898),
    'Rabat':         (34.0209,  -6.8416),
    'Fez':           (34.0181,  -5.0078),
    'Chefchaouen':   (35.1714,  -5.2636),
    'Essaouira':     (31.5085,  -9.7595),
    'Merzouga':      (31.0997,  -4.0138),
    'Tunis':         (36.8190,  10.1658),
    'Sousse':        (35.8245,  10.6346),
    'Djerba':        (33.8076,  10.8451),

    # ── Southeast Asia – extra ─────────────────────────────────────────────────
    'Koh Lanta':     ( 7.5614,  99.0460),
    'Koh Phi Phi':   ( 7.7407,  98.7784),
    'Koh Chang':     (12.0700, 102.3200),
    'Hua Hin':       (12.5684,  99.9577),
    'Pattaya':       (12.9236, 100.8825),
    'Kanchanaburi':  (14.0023,  99.5483),
    'Chiang Rai':    (19.9105,  99.8406),
    'Pai':           (19.3583,  98.4381),
    'Mui Ne':        (10.9330, 108.2869),
    'Phu Quoc':      (10.2897, 103.9840),
    'Da Lat':        (11.9404, 108.4583),
    'Can Tho':       (10.0452, 105.7469),
    'Hoi An':        (15.8801, 108.3380),
    'Lombok':        (-8.6500, 116.3242),
    'Gili Islands':  (-8.3500, 116.0500),
    'Raja Ampat':    (-0.5000, 130.5000),
    'Borobudur':     (-7.6079, 110.2038),
    'Prambanan':     (-7.7520, 110.4914),
    'Flores':        (-8.6574, 120.4408),
    'Labuan Bajo':   (-8.4962, 119.8822),
    'Toraja':        (-3.0449, 119.8612),
    'Bintan':        ( 1.1500, 104.5000),
    'Cameron Highlands': ( 4.4687, 101.3824),
    'Borneo':        ( 1.0000, 114.0000),
    'Kota Kinabalu': ( 5.9804, 116.0735),
    'Sandakan':      ( 5.8402, 118.1179),

    # ── Americas – extra ───────────────────────────────────────────────────────
    'Playa del Carmen': (20.6296, -87.0739),
    'Merida':        (20.9674, -89.6233),
    'San Cristobal de las Casas': (16.7370, -92.6376),
    'Guanajuato':    (21.0190, -101.2574),
    'Guadalajara':   (20.6597, -103.3496),
    'Puerto Vallarta': (20.6534, -105.2253),
    'Havana':        (23.1136, -82.3666),
    'Trinidad':      (21.8031, -79.9838),
    'Varadero':      (23.1526, -81.2527),
    'Antigua':       (17.1274, -61.8468),
    'Barbados':      (13.1939, -59.5432),
    'Bridgetown':    (13.0969, -59.6145),
    'St Lucia':      (13.9094, -60.9789),
    'St. Lucia':     (13.9094, -60.9789),
    'Grenada':       (12.1165, -61.6790),
    'Jamaica':       (18.1096, -77.2975),
    'Kingston':      (17.9970, -76.7936),
    'Nassau':        (25.0480, -77.3554),
    'Punta Cana':    (18.5821, -68.4043),
    'Santo Domingo': (18.4861, -69.9312),
    'San Juan':      (18.4655, -66.1057),
    'Quito':         (-0.1807, -78.4678),
    'Galapagos':     (-0.9538, -90.9656),
    'Cuenca':        (-2.9001, -79.0059),
    'Patagonia':     (-51.6230, -72.0703),
    'Torres del Paine': (-50.9423, -73.4068),
    'Easter Island': (-27.1127, -109.3497),
    'Atacama':       (-23.4700, -68.2200),
    'San Pedro de Atacama': (-22.9087, -68.2000),
    'Cartagena':     (10.3910, -75.4794),
    'Medellin':      ( 6.2442, -75.5812),
    'Bogota':        ( 4.7110, -74.0721),
    'Cali':          ( 3.4516, -76.5319),
    'Salento':       ( 4.6337, -75.5703),
    'Montevideo':    (-34.9011, -56.1645),
    'Colonia':       (-34.4626, -57.8401),
    'Manaus':        (-3.1190, -60.0217),
    'Salvador':      (-12.9714, -38.5014),
    'Natal':         (-5.7945, -35.2110),
    'Recife':        (-8.0476, -34.8770),
    'Fortaleza':     (-3.7172, -38.5433),
    'Florianopolis': (-27.5954, -48.5480),
    'Foz do Iguacu': (-25.5469, -54.5882),
    # Canada – extra
    'Jasper':        (52.8734,-118.0823),
    'Victoria':      (48.4284,-123.3656),
    'Whistler':      (50.1163,-122.9574),
    'Calgary':       (51.0447,-114.0719),
    'Niagara Falls': (43.0896, -79.0849),
    'Ottawa':        (45.4215, -75.6972),
    'Halifax':       (44.6488, -63.5752),

    # ── Oceania – extra ────────────────────────────────────────────────────────
    'Bora Bora':     (-16.5004,-151.7415),
    'Tahiti':        (-17.6509,-149.4260),
    'Papeete':       (-17.5334,-149.5667),
    'Fiji':          (-17.7134, 178.0650),
    'Nadi':          (-17.7980, 177.4130),
    'Vanuatu':       (-15.3767, 166.9592),
    'Noumea':        (-22.2758, 166.4580),
    'Great Barrier Reef': (-18.2860, 147.7000),
    'Whitsundays':   (-20.2700, 148.9800),
    'Margaret River': (-33.9530, 115.0758),
    'Hobart':        (-42.8821, 147.3272),
    'Fremantle':     (-32.0553, 115.7474),
    'Broome':        (-17.9619, 122.2363),
    'Darwin':        (-12.4634, 130.8456),
    'Abel Tasman':   (-40.9000, 172.8800),
    'Milford Sound': (-44.6718, 167.8975),
    'Franz Josef':   (-43.4000, 170.1833),
    'Waiheke Island':(-36.7879, 175.1175),

    # ── Central Asia & Caucasus ────────────────────────────────────────────────
    'Tbilisi':       (41.6938,  44.8015),
    'Batumi':        (41.6168,  41.6367),
    'Yerevan':       (40.1792,  44.4991),
    'Baku':          (40.4093,  49.8671),
    'Almaty':        (43.2220,  76.8512),
    'Nur-Sultan':    (51.1801,  71.4460),
    'Astana':        (51.1801,  71.4460),
    'Samarkand':     (39.6547,  66.9758),
    'Bukhara':       (39.7747,  64.4286),
    'Tashkent':      (41.2995,  69.2401),
    'Ashgabat':      (37.9601,  58.3261),
    'Bishkek':       (42.8746,  74.5698),

    # ── South America – extra ──────────────────────────────────────────────────
    'Mancora':       (-4.1060,  -81.0452),
    'Lake Titicaca': (-15.9254, -69.3354),
    'Puno':          (-15.8422, -70.0199),
    'Uyuni':         (-20.4630, -66.8250),
    'Salt Flats':    (-20.1338, -67.4891),
    'Sucre':         (-19.0196, -65.2619),
    'La Paz':        (-16.4897, -68.1193),
    'Trinidad and Tobago': (10.6549, -61.5019),
    'Suriname':      ( 3.9193, -56.0278),
    'Georgetown':    ( 6.8013, -58.1551),

    # ── East Africa – extra ────────────────────────────────────────────────────
    'Ngorongoro':    (-3.2041,  35.4900),
    'Kilimanjaro':   (-3.0674,  37.3556),
    'Pemba':         (-5.1167,  39.7500),
    'Ruaha':         (-7.7500,  35.0000),
    'Mafia Island':  (-7.8667,  39.8667),
    'Lamu':          (-2.2694,  40.9020),
    'Malindi':       (-3.2185,  40.1169),
    'Entebbe':       ( 0.0612,  32.4625),
    'Kampala':       ( 0.3476,  32.5825),
    'Bwindi':        (-1.0520,  29.6644),
    'Kidepo':        ( 3.8100,  33.7800),
    'Lusaka':        (-15.3875,  28.3228),
    'Livingstone':   (-17.8518,  25.8578),
    'Harare':        (-17.8252,  31.0335),
    'Windhoek':      (-22.5609,  17.0658),
    'Sossusvlei':    (-24.7272,  15.3361),
    'Swakopmund':    (-22.6784,  14.5249),
    'Etosha':        (-18.8553,  16.3264),
    'Gaborone':      (-24.6282,  25.9231),
    'Antananarivo':  (-18.8792,  47.5079),
    'Nosy Be':       (-13.3280,  48.2690),
}

# ─── Custom city persistence ────────────────────────────────────────────────────

# Merge user-added cities into the live database at import time.
CITY_COORDS.update(_db.load_all())


def add_custom_city(name: str, lat: float, lon: float) -> None:
    CITY_COORDS[name] = (lat, lon)
    _db.upsert(name, lat, lon)


def get_custom_cities() -> list:
    return sorted(
        [{'name': k, 'lat': v[0], 'lon': v[1]} for k, v in _db.load_all().items()],
        key=lambda x: x['name'].lower()
    )


def delete_custom_city(name: str) -> bool:
    CITY_COORDS.pop(name, None)
    return _db.delete(name)


# ─── Helpers ───────────────────────────────────────────────────────────────────

# In-process cache so heavy GeoDataFrames are only read once per worker.
_cache: dict = {}


def _fetch(url: str, path: str, label: str) -> None:
    if not os.path.exists(path):
        os.makedirs(DATA_DIR, exist_ok=True)
        print(f'Downloading {label}…')
        urllib.request.urlretrieve(url, path)
        print(f'  OK: {label} ready.')


def ensure_data() -> None:
    """Download all three Natural Earth files on first run."""
    _fetch(NE_URL,        NE_GEOJSON, 'countries (admin-0)')
    _fetch(NE_ADMIN1_URL, NE_ADMIN1,  'states/provinces (admin-1)')
    _fetch(NE_PLACES_URL, NE_PLACES,  'populated places')


def load_world_data() -> gpd.GeoDataFrame:
    if 'world' in _cache:
        return _cache['world']
    ensure_data()
    gdf = gpd.read_file(NE_GEOJSON)
    for src, dst in [('NAME', 'name'), ('ADMIN', 'admin'), ('CONTINENT', 'continent')]:
        if src in gdf.columns and dst not in gdf.columns:
            gdf = gdf.rename(columns={src: dst})
    _cache['world'] = gdf
    return gdf


def load_admin1_data() -> gpd.GeoDataFrame:
    if 'admin1' in _cache:
        return _cache['admin1']
    ensure_data()
    gdf = gpd.read_file(NE_ADMIN1)
    # Normalise: 'admin' = sovereign name, 'name' = state/province name
    for src, dst in [('ADMIN', 'admin'), ('NAME', 'name'), ('NAME_EN', 'name_en')]:
        if src in gdf.columns and dst not in gdf.columns:
            gdf = gdf.rename(columns={src: dst})
    _cache['admin1'] = gdf
    return gdf


def load_places_data() -> gpd.GeoDataFrame:
    if 'places' in _cache:
        return _cache['places']
    ensure_data()
    gdf = gpd.read_file(NE_PLACES)
    for src, dst in [('NAME', 'name'), ('POP_MAX', 'pop_max')]:
        if src in gdf.columns and dst not in gdf.columns:
            gdf = gdf.rename(columns={src: dst})
    _cache['places'] = gdf
    return gdf


def resolve_country_name(raw: str) -> str:
    """Normalise user input to a country/region key."""
    return COUNTRY_ALIASES.get(raw.lower().strip(), raw.strip())


def get_map_geometry(world: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    """
    Return a GeoDataFrame whose union forms the map background.
    Handles single countries and multi-country regions.
    """
    key = name.lower().strip()

    # Named region?
    if key in REGIONS:
        names = REGIONS[key]
        mask = world['name'].isin(names)
        gdf = world[mask]
        if not gdf.empty:
            return gdf

    # Single country (try alias first)
    resolved = resolve_country_name(name)
    mask = world['name'].str.lower() == resolved.lower()
    gdf = world[mask]
    if not gdf.empty:
        return gdf

    # Fuzzy: contains
    mask = world['name'].str.lower().str.contains(resolved.lower(), na=False)
    gdf = world[mask]
    if not gdf.empty:
        return gdf

    raise ValueError(f"Country/region '{name}' not found in Natural Earth data.")


def geocode_city(city: str) -> tuple[float, float] | None:
    """Return (lat, lon) from our database, or None."""
    # Exact
    if city in CITY_COORDS:
        return CITY_COORDS[city]
    # Case-insensitive
    lower = city.lower()
    for k, v in CITY_COORDS.items():
        if k.lower() == lower:
            return v
    # Partial
    for k, v in CITY_COORDS.items():
        if lower in k.lower() or k.lower() in lower:
            return v
    return None


# ─── Font selection ────────────────────────────────────────────────────────────

def _get_sans_font() -> str:
    """Return best available sans-serif font name (Inter → Segoe UI → Arial)."""
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    for preferred in ('Inter', 'Segoe UI', 'Arial', 'Helvetica', 'DejaVu Sans'):
        if preferred in available:
            return preferred
    return 'sans-serif'


# ─── Location pin ──────────────────────────────────────────────────────────────

def _draw_pin(ax, lon: float, lat: float,
              fill: str, edge: str, inner: str,
              pin_size: float, zorder: int = 8) -> None:
    """
    Draw a map-style location pin at (lon, lat).
    The pointed tip sits exactly at the city coordinate.
    pin_size   – approximate total height in data-coordinate units.
    """
    from matplotlib.patches import Circle, Polygon as MPoly

    # Geometry proportions
    w      = pin_size * 0.44   # half-width of body at shoulder
    body_h = pin_size * 0.52   # height of the triangular tail
    r      = pin_size * 0.46   # radius of the circular head
    head_cy = lat + body_h + r  # vertical centre of the pin head

    # Triangle body (tip → shoulders)
    body = MPoly(
        [[lon,       lat],
         [lon - w,   lat + body_h],
         [lon + w,   lat + body_h]],
        closed=True,
        facecolor=fill,
        edgecolor=edge,
        linewidth=1.0,
        zorder=zorder,
        clip_on=True,
    )
    ax.add_patch(body)

    # Circular head
    head = Circle(
        (lon, head_cy), r,
        facecolor=fill,
        edgecolor=edge,
        linewidth=1.0,
        zorder=zorder,
        clip_on=True,
    )
    ax.add_patch(head)

    # Inner white ring (gives the classic pin look)
    ax.add_patch(Circle(
        (lon, head_cy), r * 0.38,
        facecolor=inner,
        edgecolor='none',
        zorder=zorder + 1,
        clip_on=True,
    ))


# ─── Arced route segment ───────────────────────────────────────────────────────

def _draw_arc_segment(ax, x1: float, y1: float,
                      x2: float, y2: float,
                      color: str, lw: float,
                      curvature: float, map_diag: float,
                      zorder: int = 5) -> None:
    """
    Draw a dashed quadratic-bezier arc from (x1,y1)→(x2,y2).
    Samples the bezier into 80 points and draws as a dashed ax.plot,
    which correctly handles linestyle dashes on curved paths.
    """
    mx, my   = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy   = x2 - x1, y2 - y1
    seg_len  = math.hypot(dx, dy) or 1e-9

    # Perpendicular direction (90° CCW of travel direction)
    px, py  = -dy / seg_len, dx / seg_len
    cpx     = mx + px * seg_len * curvature   # control point
    cpy     = my + py * seg_len * curvature

    # Sample the quadratic bezier B(t) = (1-t)²P0 + 2t(1-t)Pc + t²P2
    t        = np.linspace(0.0, 1.0, 80)
    bx_arr   = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cpx + t ** 2 * x2
    by_arr   = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cpy + t ** 2 * y2

    ax.plot(bx_arr, by_arr,
            color=color, linewidth=lw,
            linestyle=(0, (7, 5)),   # dashed
            solid_capstyle='round',
            zorder=zorder)

    # Arrowhead at curve midpoint
    mid      = len(bx_arr) // 2
    bxm, bym = bx_arr[mid], by_arr[mid]
    tdx      = bx_arr[mid + 1] - bx_arr[mid - 1]
    tdy      = by_arr[mid + 1] - by_arr[mid - 1]
    tlen     = math.hypot(tdx, tdy) or 1e-9
    eps      = map_diag * 0.004
    ax.annotate(
        '',
        xy    =(bxm + tdx / tlen * eps, bym + tdy / tlen * eps),
        xytext=(bxm - tdx / tlen * eps, bym - tdy / tlen * eps),
        arrowprops=dict(arrowstyle='-|>', color=color,
                        lw=1.6, mutation_scale=11),
        zorder=zorder + 1,
    )


# ─── Road network ──────────────────────────────────────────────────────────────

def _draw_road_network(ax, x0: float, x1: float,
                       y0: float, y1: float,
                       route_names: set,
                       map_w: float, map_h: float) -> None:
    """
    Draw a subtle grey road-network connecting nearby cities in the viewport.
    Uses a KNN approach: each city connects to its 3 nearest neighbours
    within a distance threshold.
    """
    in_view = [
        (name, lat, lon)
        for name, (lat, lon) in CITY_COORDS.items()
        if x0 <= lon <= x1 and y0 <= lat <= y1
    ]
    if len(in_view) < 2:
        return

    drawn:  set = set()
    # Tighter distance cap — prevents wide triangular connections between
    # distant cities that make the road layer look like geometric artifacts.
    max_d   = max(map_w, map_h) * 0.18

    for n1, lat1, lon1 in in_view:
        neighbours = sorted(
            (math.hypot(lon2 - lon1, lat2 - lat1), n2, lat2, lon2)
            for n2, lat2, lon2 in in_view if n2 != n1
        )
        # Connect to 2 nearest neighbours only (was 3)
        for dist, n2, lat2, lon2 in neighbours[:2]:
            if dist > max_d:
                break
            edge = tuple(sorted((n1, n2)))
            if edge in drawn:
                continue
            drawn.add(edge)
            ax.plot([lon1, lon2], [lat1, lat2],
                    color=PALETTE['road'],
                    linewidth=0.4,
                    alpha=0.38,
                    solid_capstyle='round',
                    zorder=3)


# ─── Main map generator ────────────────────────────────────────────────────────

def generate_map(cities_input: list[str], country_name: str,
                 bounds: dict | None = None) -> bytes:
    """
    Render a luxury route map and return raw JPEG bytes.

    Parameters
    ----------
    cities_input : ordered list of city names
    country_name : country name or region key
    bounds       : optional {north, south, east, west} from the Leaflet viewport.
                   When supplied the map is rendered at exactly that extent.
                   When None the full country extent is used (first-draft behaviour).
    """
    world       = load_world_data()
    country_gdf = get_map_geometry(world, country_name)
    admin1      = load_admin1_data()
    places      = load_places_data()
    sans_font   = _get_sans_font()

    # ── Collect route coords ────────────────────────────────────────────────────
    route: list[tuple[str, float, float]] = []
    missing: list[str] = []
    for city in cities_input:
        coords = geocode_city(city.strip())
        if coords:
            route.append((city.strip(), coords[0], coords[1]))
        else:
            missing.append(city.strip())

    # ── Viewport ────────────────────────────────────────────────────────────────
    if bounds:
        # Use the exact Leaflet viewport the user was looking at
        x0, x1 = bounds['west'],  bounds['east']
        y0, y1 = bounds['south'], bounds['north']
    else:
        # Default: full country extent (first-draft behaviour)
        cminx, cminy, cmaxx, cmaxy = country_gdf.total_bounds
        cw, ch = cmaxx - cminx, cmaxy - cminy
        pad_x  = max(cw * 0.10, 0.5)
        pad_y  = max(ch * 0.10, 0.5)
        x0, x1 = cminx - pad_x, cmaxx + pad_x
        y0, y1 = cminy - pad_y, cmaxy + pad_y

    map_w    = x1 - x0
    map_h    = y1 - y0
    map_diag = math.hypot(map_w, map_h)

    # ── Figure — Mercator-corrected aspect so the output matches Leaflet exactly ─
    # Leaflet uses Web Mercator: at latitude φ, 1° lon = cos(φ) × (1° lat) visually.
    # We compute the figure shape from the bounds so that xlim/ylim fill the axes
    # completely — no equal-aspect shrinkage, no bbox_inches cropping surprises.
    lat_mid   = (y0 + y1) / 2
    merc_cos  = max(0.15, abs(math.cos(math.radians(lat_mid))))
    geo_aspect = (map_w * merc_cos) / max(map_h, 0.001)

    fig_h = 9.0
    fig_w = max(7.0, min(18.0, fig_h * geo_aspect))

    # Tight margins — axes fills the figure; decorative border sits just inside
    MARGIN = 0.03   # fraction of figure
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor=PALETTE['background'])
    plt.subplots_adjust(left=MARGIN, right=1 - MARGIN,
                        top=1 - MARGIN, bottom=MARGIN)

    ax.set_facecolor(PALETTE['ocean'])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    # NO set_aspect — the figure shape drives the aspect ratio so xlim/ylim
    # map 1-to-1 onto the pixel grid, matching the Leaflet viewport exactly.
    ax.set_axis_off()

    # ── z=1  World background ──────────────────────────────────────────────────
    world.plot(ax=ax, color=PALETTE['bg_world'],
               edgecolor=PALETTE['bg_world_edge'], linewidth=0.3, zorder=1)

    # ── z=2  Country / region fill + outer border ─────────────────────────────
    country_gdf.plot(ax=ax, color=PALETTE['land_fill'],
                     edgecolor=PALETTE['border'], linewidth=1.2, zorder=2)

    # ── z=3  State / province borders — clipped to viewport ───────────────────
    from shapely.geometry import box as _shapely_box

    # Match admin-1 rows to the rendered country using the ISO 3-letter code
    # (adm0_a3 in the 50m admin-1 dataset).  Fall back to name matching if
    # the column is absent or yields no rows.
    iso3_set = set()
    for col in ('ADM0_A3', 'adm0_a3', 'ISO_A3', 'iso_a3'):
        if col in country_gdf.columns:
            iso3_set = {str(v).upper() for v in country_gdf[col].dropna()}
            break

    states = gpd.GeoDataFrame()
    if iso3_set:
        for col in ('adm0_a3', 'ADM0_A3', 'gu_a3', 'GU_A3'):
            if col in admin1.columns:
                states = admin1[admin1[col].str.upper().isin(iso3_set)]
                if not states.empty:
                    break

    # Fallback: match by sovereign country name via admin column
    if states.empty:
        # Find the name column case-insensitively — avoids KeyError on 'NAME' vs 'name'
        _name_col = next((c for c in country_gdf.columns if c.lower() == 'name'), None)
        sov_names_lower = (
            {str(n).lower() for n in country_gdf[_name_col].tolist()}
            if _name_col else set()
        )
        for col in ('admin', 'Admin', 'ADMIN', 'geonunit', 'name', 'NAME'):
            if col in admin1.columns:
                candidate = admin1[admin1[col].str.lower().isin(sov_names_lower)]
                if not candidate.empty:
                    states = candidate
                    break

    if not states.empty:
        try:
            # Clip polygons to viewport — eliminates the triangular-line artefacts
            # caused by coarse 110 m polygons extending far outside the view.
            vp_box        = _shapely_box(x0, y0, x1, y1)
            states_clipped = gpd.clip(states, vp_box)
        except Exception:
            states_clipped = states   # fall back gracefully

        if not states_clipped.empty:
            states_clipped.plot(ax=ax, facecolor='none',
                                edgecolor='#AAAAAA', linewidth=0.55,
                                linestyle=(0, (6, 4)), alpha=0.7, zorder=3)

        # Labels — only at centroids that fall inside the viewport
        name_col_a1 = next((c for c in ('name', 'name_en', 'NAME') if c in states.columns), 'name')
        lbl_fs = max(5.0, min(9.0, map_h * 0.30))
        for _, row in states.iterrows():
            try:
                c = row.geometry.centroid
            except Exception:
                continue
            if not (x0 <= c.x <= x1 and y0 <= c.y <= y1):
                continue
            lbl = str(row.get(name_col_a1, '') or '').strip()
            if not lbl:
                continue
            ax.text(c.x, c.y, lbl.upper(),
                    fontsize=lbl_fs, fontfamily=sans_font, fontweight='normal',
                    color='#BBBBBB', ha='center', va='center', alpha=0.80, zorder=4,
                    path_effects=[pe.withStroke(linewidth=1.5,
                                                foreground=PALETTE['background'])])

    # ── z=3  Road network ──────────────────────────────────────────────────────
    route_names = {r[0] for r in route}
    _draw_road_network(ax, x0, x1, y0, y1, route_names, map_w, map_h)

    # ── z=4  Country name watermark ────────────────────────────────────────────
    union_geom = (country_gdf.geometry.union_all()
                  if hasattr(country_gdf.geometry, 'union_all')
                  else country_gdf.geometry.unary_union)
    ctrd   = union_geom.centroid
    cx_lbl = max(x0 + map_w * 0.1, min(x1 - map_w * 0.1, ctrd.x))
    cy_lbl = max(y0 + map_h * 0.1, min(y1 - map_h * 0.1, ctrd.y))
    ax.text(cx_lbl, cy_lbl, country_name.upper(),
            fontsize=max(11, min(26, map_h * 1.5)),
            fontfamily='serif', fontstyle='italic', fontweight='light',
            color=PALETTE['country_name'], alpha=0.20,
            ha='center', va='center', zorder=4)

    # ── z=5  Populated-place labels (Natural Earth, non-route cities) ──────────
    name_col_p = 'name'    if 'name'    in places.columns else 'NAME'
    pop_col_p  = 'pop_max' if 'pop_max' in places.columns else None

    places_view = places[
        (places.geometry.x >= x0) & (places.geometry.x <= x1) &
        (places.geometry.y >= y0) & (places.geometry.y <= y1)
    ].copy()

    if pop_col_p and pop_col_p in places_view.columns:
        places_view = places_view.sort_values(pop_col_p, ascending=False)

    route_latlons      = [(lat, lon) for _, lat, lon in route]
    route_names_lower  = {n.lower() for n in route_names}
    # proximity threshold in degrees — excludes aliases like "New Delhi" near "Delhi"
    PROX = max(0.6, map_diag * 0.015)

    shown = 0
    for _, row in places_view.iterrows():
        if shown >= 22:
            break
        city_nm = str(row.get(name_col_p, '') or '').strip()
        if not city_nm:
            continue
        lon_p, lat_p = row.geometry.x, row.geometry.y

        # Skip route cities (by name) and anything too close to a pin
        if city_nm.lower() in route_names_lower:
            continue
        if any(math.hypot(lon_p - rlon, lat_p - rlat) < PROX
               for rlat, rlon in route_latlons):
            continue

        pop = int(row[pop_col_p]) if pop_col_p and pop_col_p in row.index else 0
        if   pop > 3_000_000: fs, fw = max(7.5, map_h * 0.40), 'semibold'
        elif pop >   800_000: fs, fw = max(6.5, map_h * 0.34), 'normal'
        else:                 fs, fw = max(5.5, map_h * 0.28), 'normal'

        ax.text(lon_p, lat_p, city_nm,
                fontsize=fs, fontfamily=sans_font, fontweight=fw,
                color=PALETTE['other_city'], ha='center', va='center',
                alpha=0.85, zorder=5,
                path_effects=[pe.withStroke(linewidth=1.8,
                                            foreground=PALETTE['background'])])
        shown += 1

    # ── z=6  Arced dashed route lines ─────────────────────────────────────────
    if len(route) >= 2:
        for i in range(len(route) - 1):
            _draw_arc_segment(ax,
                              route[i][2],     route[i][1],
                              route[i + 1][2], route[i + 1][1],
                              color=PALETTE['route'], lw=2.4,
                              curvature=0.13, map_diag=map_diag, zorder=6)

    # ── z=8  Location pins + bold labels ──────────────────────────────────────
    # Pin size: fixed fraction of viewport HEIGHT so it stays proportional
    # regardless of zoom level. Clamped to a sane range.
    pin_size = max(0.25, min(1.8, map_h * 0.028))

    placed: list[tuple[float, float]] = []
    for city_nm, lat, lon in route:
        _draw_pin(ax, lon, lat,
                  fill=PALETTE['city_face'],
                  edge=PALETTE['city_edge'],
                  inner=PALETTE['city_inner'],
                  pin_size=pin_size, zorder=8)

        # Label beside the pin head
        pr = pin_size * 0.46
        ph = pin_size * 0.52
        lx = lon + pr * 1.7
        ly = lat + ph + pr

        for plx, ply in placed:
            if abs(lx - plx) < map_w * 0.08 and abs(ly - ply) < map_h * 0.05:
                ly -= map_h * 0.04
        placed.append((lx, ly))

        ax.text(lx, ly, city_nm,
                fontsize=max(7.5, map_h * 0.42),
                fontfamily=sans_font, fontweight='bold',
                color=PALETTE['label'], ha='left', va='center', zorder=10,
                path_effects=[pe.withStroke(linewidth=2.8,
                                            foreground=PALETTE['background'])])

    # ── Decorative gold border ─────────────────────────────────────────────────
    bm, im = 0.016, 0.024
    for margin, lw, alpha in [(bm, 2.2, 1.0), (im, 0.6, 0.65)]:
        fig.add_artist(plt.Rectangle(
            (margin, margin), 1 - 2 * margin, 1 - 2 * margin,
            fill=False, edgecolor=PALETTE['deco_border'],
            linewidth=lw, alpha=alpha,
            transform=fig.transFigure, zorder=20, clip_on=False))

    # ── Export — no bbox_inches so the saved image = exactly the figure ────────
    buf = BytesIO()
    fig.savefig(buf, format='jpeg', dpi=220,
                facecolor=PALETTE['background'],
                pil_kwargs={'quality': 95, 'subsampling': 0})
    plt.close(fig)
    buf.seek(0)
    if missing:
        print(f'Warning – cities not in database: {missing}')
    return buf.read()
