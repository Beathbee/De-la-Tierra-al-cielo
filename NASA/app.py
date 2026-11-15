"""
Luna vs Marte desde cualquier ciudad del mundo
Datos: NASA/JPL Horizons (posición, distancia, brillo, iluminación)
       NASA Image and Video Library (imágenes)
Geocodificación: Open-Meteo (gratis, sin clave)
Ejecutar:  streamlit run app.py
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
NASA_IMAGES_URL = "https://images-api.nasa.gov/search"
AU_KM = 149_597_870.7

BODIES = {"Luna": "301", "Marte": "499"}

# Datos físicos de las hojas de datos (Fact Sheets) de la NASA
PHYSICAL = pd.DataFrame(
    {
        "Luna": [
            "3.474,8 km", "1,62 m/s²", "29,53 días (día solar)",
            "27,3 días (alrededor de la Tierra)", "-173 °C a 127 °C",
            "Casi nula (exosfera)", "384.400 km (de la Tierra)",
        ],
        "Marte": [
            "6.779 km", "3,71 m/s²", "24 h 39 min (sol)",
            "687 días terrestres (alrededor del Sol)", "-140 °C a 20 °C (media -63 °C)",
            "95 % CO₂, ~6 mbar", "54,6 a 401 millones de km (de la Tierra)",
        ],
    },
    index=[
        "Diámetro", "Gravedad superficial", "Duración del día",
        "Período orbital", "Temperatura superficial", "Atmósfera",
        "Distancia a la Tierra",
    ],
)


# ---------------------------------------------------------------- Datos
@st.cache_data(ttl=3600)
def buscar_ciudad(nombre: str):
    r = requests.get(
        GEOCODING_URL,
        params={"name": nombre, "count": 5, "language": "es"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("results", [])


@st.cache_data(ttl=600)
def horizons(codigo: str, lat: float, lon: float, inicio: str, fin: str) -> pd.DataFrame:
    """Efemérides desde un punto de la Tierra (observador topocéntrico)."""
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
        "QUANTITIES": "'4,9,10,20,21'",  # az/elev, magnitud, iluminación, distancia, luz
        "CSV_FORMAT": "'YES'",
        "ANG_FORMAT": "'DEG'",
    }
    r = requests.get(HORIZONS_URL, params=params, timeout=30)
    r.raise_for_status()
    texto = r.json().get("result", "")
    if "$$SOE" not in texto:
        raise ValueError("Horizons no devolvió datos:\n" + texto[:500])

    antes, resto = texto.split("$$SOE")
    filas = resto.split("$$EOE")[0].strip().splitlines()
    cabecera = [l for l in antes.splitlines() if "Date" in l][-1]
    cols = [c.strip() for c in cabecera.split(",")]

    df = pd.DataFrame([[c.strip() for c in f.split(",")] for f in filas])
    df = df.iloc[:, : len(cols)]
    df.columns = cols[: df.shape[1]]

    def col(prefijo):
        return next(c for c in df.columns if c.startswith(prefijo))

    out = pd.DataFrame(
        {
            "hora_utc": pd.to_datetime(df[col("Date")], format="%Y-%b-%d %H:%M", errors="coerce"),
            "azimut": pd.to_numeric(df[col("Azi")], errors="coerce"),
            "elevacion": pd.to_numeric(df[col("Elev")], errors="coerce"),
            "magnitud": pd.to_numeric(df[col("APmag")], errors="coerce")
            if any(c.startswith("APmag") for c in df.columns)
            else pd.to_numeric(df[col("Vmag")], errors="coerce"),
            "iluminacion_pct": pd.to_numeric(df[col("Illu")], errors="coerce"),
            "distancia_km": pd.to_numeric(df[col("delta")], errors="coerce") * AU_KM,
            "luz_min": pd.to_numeric(df[col("1-way")], errors="coerce"),
        }
    )
    return out


@st.cache_data(ttl=3600)
def imagenes_nasa(consulta: str, n: int = 3):
    r = requests.get(
        NASA_IMAGES_URL, params={"q": consulta, "media_type": "image"}, timeout=20
    )
    r.raise_for_status()
    items = r.json()["collection"]["items"][:n]
    return [
        (i["links"][0]["href"], i["data"][0]["title"])
        for i in items
        if i.get("links")
    ]


def cardinal(az: float) -> str:
    pts = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    return pts[int((az + 22.5) // 45) % 8]


# ------------------------------------------------------------------ UI
st.set_page_config(page_title="Luna vs Marte", page_icon="🌙", layout="wide")
st.title("🌙 Luna vs Marte 🔴")
st.caption("Compara ambos cuerpos desde cualquier ciudad del mundo · datos NASA/JPL")

with st.sidebar:
    st.header("📍 Ubicación")
    nombre = st.text_input("Ciudad", value="Temuco")
    resultados = []
    try:
        resultados = buscar_ciudad(nombre) if nombre.strip() else []
    except Exception as e:
        st.error(f"No pude buscar la ciudad: {e}")

    if not resultados:
        st.warning("Escribe una ciudad válida.")
        st.stop()

    etiquetas = [
        f"{c['name']}, {c.get('admin1', '')}, {c.get('country', '')}" for c in resultados
    ]
    elegido = resultados[etiquetas.index(st.selectbox("Resultado", etiquetas))]
    lat, lon = elegido["latitude"], elegido["longitude"]
    st.write(f"Lat: **{lat:.3f}** · Lon: **{lon:.3f}**")

    st.header("🕒 Fecha")
    fecha = st.date_input("Día (UTC)", value=datetime.now(timezone.utc).date())

inicio = datetime.combine(fecha, datetime.min.time())
fin = inicio + timedelta(hours=24)
fmt = "%Y-%m-%d %H:%M"

datos = {}
try:
    for cuerpo, cod in BODIES.items():
        datos[cuerpo] = horizons(cod, lat, lon, inicio.strftime(fmt), fin.strftime(fmt))
except Exception as e:
    st.error(f"Error consultando NASA/JPL Horizons: {e}")
    st.stop()

# hora actual (o del mediodía si se eligió otro día)
ahora = datetime.now(timezone.utc).replace(tzinfo=None)
idx = min(max(int((ahora - inicio).total_seconds() // 3600), 0), 23) if inicio.date() == ahora.date() else 12

st.subheader(f"Desde {elegido['name']} — {datos['Luna'].hora_utc[idx]:%d/%m/%Y %H:%M} UTC")

c1, c2 = st.columns(2)
for col, cuerpo in zip((c1, c2), BODIES):
    d = datos[cuerpo].iloc[idx]
    with col:
        st.markdown(f"### {'🌙' if cuerpo == 'Luna' else '🔴'} {cuerpo}")
        visible = d.elevacion > 0
        st.metric("Elevación", f"{d.elevacion:.1f}°", "Sobre el horizonte" if visible else "Bajo el horizonte")
        st.metric("Dirección", f"{d.azimut:.0f}° ({cardinal(d.azimut)})")
        st.metric("Distancia", f"{d.distancia_km:,.0f} km".replace(",", "."))
        st.metric("Luz tarda", f"{d.luz_min:.2f} min" if d.luz_min < 60 else f"{d.luz_min:.1f} min")
        st.metric("Magnitud aparente", f"{d.magnitud:.2f}")
        st.metric("Iluminación", f"{d.iluminacion_pct:.1f} %")

st.subheader("📈 Elevación sobre el horizonte (24 h)")
graf = pd.DataFrame(
    {c: datos[c].set_index("hora_utc")["elevacion"] for c in BODIES}
)
st.line_chart(graf)
st.caption("Valores por encima de 0° = el astro está visible en el cielo.")

st.subheader("🪐 Comparación física")
st.table(PHYSICAL)

st.subheader("🖼️ Imágenes de la NASA")
i1, i2 = st.columns(2)
for col, (cuerpo, q) in zip((i1, i2), (("Luna", "moon surface"), ("Marte", "mars surface rover"))):
    with col:
        st.markdown(f"**{cuerpo}**")
        try:
            for url, titulo in imagenes_nasa(q):
                st.image(url, caption=titulo)
        except Exception as e:
            st.info(f"No se pudieron cargar imágenes: {e}")
