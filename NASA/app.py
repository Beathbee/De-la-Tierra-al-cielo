import os
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
NASA_IMAGES_URL = "https://images-api.nasa.gov/search"
AU_KM = 149_597_870.7
BODIES = {"Luna": "301", "Marte": "499"}

PHYSICAL = [
    ("Diámetro", "3.474,8 km", "6.779 km"),
    ("Gravedad superficial", "1,62 m/s²", "3,71 m/s²"),
    ("Duración del día", "29,53 días terrestres", "24 h 39 min"),
    ("Período orbital", "27,3 días (alrededor de la Tierra)", "687 días (alrededor del Sol)"),
    ("Temperatura", "-173 °C a 127 °C", "-140 °C a 20 °C (media -63 °C)"),
    ("Atmósfera", "Casi nula (exosfera)", "95 % CO₂, ~6 mbar"),
    ("Distancia a la Tierra", "384.400 km", "54,6 a 401 millones de km"),
]


def horizons(codigo, lat, lon, inicio, fin):
    params = {
        "format": "json",
        "COMMAND": f"'{codigo}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon},{lat},0'",
        "START_TIME": f"'{inicio}'",
        "STOP_TIME": f"'{fin}'",
        "STEP_SIZE": "'1h'",
        "QUANTITIES": "'4,9,10,20,21'",
        "CSV_FORMAT": "'YES'",
        "ANG_FORMAT": "'DEG'",
    }
    r = requests.get(HORIZONS_URL, params=params, timeout=30)
    r.raise_for_status()
    texto = r.json().get("result", "")
    if "$$SOE" not in texto:
        raise ValueError("Horizons no devolvió datos: " + texto[:300])

    antes, resto = texto.split("$$SOE")
    filas = resto.split("$$EOE")[0].strip().splitlines()
    cabecera = [l for l in antes.splitlines() if "Date" in l][-1]
    cols = [c.strip() for c in cabecera.split(",")]

    def idx(*prefijos):
        for p in prefijos:
            for i, c in enumerate(cols):
                if c.startswith(p):
                    return i
        raise KeyError(prefijos)

    i_f, i_az, i_el = idx("Date"), idx("Azi"), idx("Elev")
    i_mag, i_ill = idx("APmag", "Vmag"), idx("Illu")
    i_d, i_lt = idx("delta"), idx("1-way")

    out = []
    for f in filas:
        c = [x.strip() for x in f.split(",")]
        out.append({
            "hora": c[i_f],
            "azimut": float(c[i_az]),
            "elevacion": float(c[i_el]),
            "magnitud": float(c[i_mag]),
            "iluminacion": float(c[i_ill]),
            "distancia_km": float(c[i_d]) * AU_KM,
            "luz_min": float(c[i_lt]),
        })
    return out


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ciudades")
def ciudades():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    r = requests.get(GEOCODING_URL, params={"name": q, "count": 6, "language": "es"}, timeout=15)
    r.raise_for_status()
    return jsonify([
        {"nombre": c["name"], "region": c.get("admin1", ""), "pais": c.get("country", ""),
         "lat": c["latitude"], "lon": c["longitude"]}
        for c in r.json().get("results", [])
    ])


@app.route("/api/comparar")
def comparar():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
        fecha = request.args.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        inicio = datetime.strptime(fecha, "%Y-%m-%d")
    except (KeyError, ValueError):
        return jsonify({"error": "Parámetros inválidos"}), 400

    fin = inicio + timedelta(hours=24)
    fmt = "%Y-%m-%d %H:%M"
    try:
        datos = {n: horizons(c, lat, lon, inicio.strftime(fmt), fin.strftime(fmt))
                 for n, c in BODIES.items()}
    except Exception as e:
        return jsonify({"error": f"Error consultando NASA/JPL: {e}"}), 502
    return jsonify({"datos": datos, "fisico": PHYSICAL})


@app.route("/api/imagenes")
def imagenes():
    q = request.args.get("q", "moon")
    try:
        r = requests.get(NASA_IMAGES_URL, params={"q": q, "media_type": "image"}, timeout=20)
        r.raise_for_status()
        items = r.json()["collection"]["items"][:3]
        return jsonify([{"url": i["links"][0]["href"], "titulo": i["data"][0]["title"]}
                        for i in items if i.get("links")])
    except Exception:
        return jsonify([])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)