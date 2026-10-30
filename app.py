"""
Previsión de Ventas para Mortales 📊
Sube tus ventas, mira si vas a llegar al objetivo del mes y pide consejo a la IA.
"""
import json
import os
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Previsión de Ventas para Mortales", page_icon="📊", layout="wide")

RUTA_EJEMPLO = Path(__file__).parent / "data" / "ventas_ejemplo.csv"

# Nombres de columna que reconocemos (sin tildes y en minúsculas)
SINONIMOS = {
    "fecha": ["fecha", "fecha factura", "fecha pedido", "fecha venta", "date", "dia", "fecha_factura"],
    "importe": ["importe", "importe neto", "ventas", "venta", "total", "facturacion", "amount",
                "sales", "importe_neto", "neto", "valor"],
    "comercial": ["comercial", "vendedor", "agente", "representante", "sales rep", "seller"],
    "cliente": ["cliente", "customer", "razon social", "nombre cliente", "tienda", "optica"],
}


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def eur(x: float) -> str:
    """12345.6 -> '12.346 €'"""
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.0f} €".replace(",", ".")


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return texto.strip().lower().replace("_", " ")


def dias_laborables(desde: date, hasta: date) -> int:
    """Días laborables (lunes-viernes) entre desde y hasta, ambos incluidos."""
    if hasta < desde:
        return 0
    return int(np.busday_count(desde, hasta + timedelta(days=1)))


def fin_de_mes(d: date) -> date:
    return (pd.Timestamp(d) + pd.offsets.MonthEnd(0)).date()


def a_numero(serie: pd.Series) -> pd.Series:
    """Convierte importes tipo '1.234,56', '1234.56' o '1 234 €' a número."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)
    s = serie.astype(str).str.replace("€", "", regex=False).str.replace(" ", "", regex=False).str.strip()
    coma_decimal = s.str.contains(r",\d{1,2}$", regex=True)
    s = s.where(~coma_decimal, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def a_fecha(serie: pd.Series) -> pd.Series:
    """Entiende fechas ISO (2026-10-15), españolas (15/10/2026) y fechas de Excel."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie
    s = serie.astype(str).str.strip()
    es_iso = s.str.match(r"^\d{4}-\d{1,2}-\d{1,2}").mean() > 0.5
    if es_iso:
        return pd.to_datetime(s, errors="coerce", format="ISO8601")
    return pd.to_datetime(s, errors="coerce", dayfirst=True, format="mixed")


# ----------------------------------------------------------------------------
# Carga y limpieza de datos
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def leer_fichero(contenido: bytes, nombre: str) -> pd.DataFrame:
    import io
    if not contenido or not contenido.strip():
        raise ValueError("El fichero está vacío.")
    if nombre.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(contenido))
    texto = contenido.decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(texto), sep=None, engine="python")


def preparar_datos(bruto: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Detecta columnas, limpia y devuelve (datos, avisos). Lanza ValueError si no se puede usar."""
    avisos = []
    if bruto is None or bruto.empty:
        raise ValueError("El fichero está vacío.")

    columnas = {}
    for col in bruto.columns:
        clave = normalizar(col)
        for destino, opciones in SINONIMOS.items():
            if destino not in columnas and clave in opciones:
                columnas[destino] = col
    faltan = [c for c in ("fecha", "importe") if c not in columnas]
    if faltan:
        raise ValueError(
            f"No encuentro la(s) columna(s) **{', '.join(faltan)}**. "
            f"Columnas del fichero: {', '.join(map(str, bruto.columns))}. "
            "Renombra la columna de fechas a `fecha` y la de euros a `importe` y vuelve a subirlo."
        )

    df = pd.DataFrame()
    df["fecha"] = a_fecha(bruto[columnas["fecha"]])
    df["importe"] = a_numero(bruto[columnas["importe"]])
    df["comercial"] = bruto[columnas["comercial"]].astype(str).str.strip() if "comercial" in columnas else "Todo el equipo"
    df["cliente"] = bruto[columnas["cliente"]].astype(str).str.strip() if "cliente" in columnas else None

    malas_fechas = int(df["fecha"].isna().sum())
    malos_importes = int(df["importe"].isna().sum())
    if malas_fechas:
        avisos.append(f"He descartado {malas_fechas} fila(s) con una fecha que no entiendo.")
    if malos_importes:
        avisos.append(f"He descartado {malos_importes} fila(s) con un importe que no es un número.")
    df = df.dropna(subset=["fecha", "importe"])
    if df.empty:
        raise ValueError("Después de limpiar no queda ninguna fila válida. Revisa el formato de fechas e importes.")
    if "cliente" not in columnas:
        avisos.append("No hay columna de cliente: no podré buscar clientes dormidos.")
    df["fecha"] = df["fecha"].dt.normalize()
    return df, avisos


# ----------------------------------------------------------------------------
# Previsión
# ----------------------------------------------------------------------------
def prever_cierre(df: pd.DataFrame, corte: date) -> dict:
    """Proyecta el cierre del mes de 'corte' con dos métodos y devuelve un diccionario."""
    inicio = corte.replace(day=1)
    fin = fin_de_mes(corte)
    ts_inicio, ts_corte = pd.Timestamp(inicio), pd.Timestamp(corte)
    vendido = float(df.loc[(df["fecha"] >= ts_inicio) & (df["fecha"] <= ts_corte), "importe"].sum())
    transcurridos = dias_laborables(inicio, corte)
    totales = dias_laborables(inicio, fin)

    # Fracción del mes vendida a estas alturas en los meses completos anteriores
    fracciones, totales_previos = [], []
    for k in range(1, 7):
        m_ini = (pd.Timestamp(inicio) - pd.DateOffset(months=k)).date()
        m_fin = fin_de_mes(m_ini)
        if pd.Timestamp(m_ini) < df["fecha"].min().replace(day=1):
            break
        mes = df[(df["fecha"] >= pd.Timestamp(m_ini)) & (df["fecha"] <= pd.Timestamp(m_fin))]
        total = mes["importe"].sum()
        totales_previos.append(total)
        if total <= 0:
            continue
        # Corte equivalente: el día con el mismo número de días laborables transcurridos
        dias_mes = pd.bdate_range(m_ini, m_fin)
        if transcurridos == 0:
            fracciones.append(0.0)
            continue
        dia_equiv = dias_mes[min(transcurridos, len(dias_mes)) - 1]
        fracciones.append(mes.loc[mes["fecha"] <= dia_equiv, "importe"].sum() / total)

    media_historica = float(np.mean(totales_previos[:3])) if totales_previos else 0.0
    prev_ritmo = prev_hist = None
    if corte >= fin or transcurridos >= totales:
        prevision, bajo, alto, metodo = vendido, vendido, vendido, "mes cerrado"
    elif transcurridos == 0:
        prevision = bajo = alto = max(media_historica, vendido)
        metodo = "media de los últimos meses (aún no ha pasado ningún día laborable)"
    else:
        prev_ritmo = vendido / transcurridos * totales
        frac = float(np.median(fracciones)) if fracciones else 0
        if frac > 0.02:
            prev_hist = vendido / frac
            prevision = (prev_ritmo + prev_hist) / 2
            bajo, alto = min(prev_ritmo, prev_hist), max(prev_ritmo, prev_hist)
            metodo = "media de ritmo actual y patrón histórico"
        else:
            prevision = bajo = alto = prev_ritmo
            metodo = "solo ritmo actual (no hay meses anteriores completos)"
    return {
        "inicio": inicio, "fin": fin, "vendido": vendido, "prevision": max(prevision, vendido),
        "bajo": max(bajo, vendido), "alto": max(alto, vendido), "metodo": metodo,
        "prev_ritmo": prev_ritmo, "prev_hist": prev_hist,
        "dias_transcurridos": transcurridos, "dias_totales": totales,
        "dias_restantes": max(totales - transcurridos, 0), "media_3_meses": media_historica,
        "meses_historicos": len(fracciones),
    }


def objetivo_sugerido(df: pd.DataFrame, corte: date) -> float:
    inicio = pd.Timestamp(corte.replace(day=1))
    hace_un_año = inicio - pd.DateOffset(years=1)
    mes_pasado = df[(df["fecha"] >= hace_un_año) & (df["fecha"] <= hace_un_año + pd.offsets.MonthEnd(0))]
    if not mes_pasado.empty:
        base = mes_pasado["importe"].sum() * 1.10
    else:
        previos = df[df["fecha"] < inicio]
        if previos.empty:
            return 10000.0
        por_mes = previos.groupby(previos["fecha"].dt.to_period("M"))["importe"].sum().tail(3)
        base = por_mes.mean() * 1.05
    return float(max(1000, round(base / 1000) * 1000))


def clientes_dormidos(df: pd.DataFrame, corte: date) -> pd.DataFrame:
    """Clientes que compraron en cada uno de los 3 meses anteriores y este mes todavía no."""
    if df["cliente"].isna().all():
        return pd.DataFrame()
    inicio = pd.Timestamp(corte.replace(day=1))
    hace3 = inicio - pd.DateOffset(months=3)
    previos = df[(df["fecha"] >= hace3) & (df["fecha"] < inicio)].copy()
    previos["mes"] = previos["fecha"].dt.to_period("M")
    meses = previos.groupby("cliente")["mes"].nunique()
    fieles = meses[meses >= 3].index
    este_mes = set(df[(df["fecha"] >= inicio) & (df["fecha"] <= pd.Timestamp(corte))]["cliente"])
    dormidos = [c for c in fieles if c not in este_mes]
    if not dormidos:
        return pd.DataFrame()
    t = (previos[previos["cliente"].isin(dormidos)]
         .groupby(["cliente", "comercial"], as_index=False)
         .agg(compra_media_mes=("importe", "sum"), ultima_compra=("fecha", "max")))
    t["compra_media_mes"] = t["compra_media_mes"] / 3
    return t.sort_values("compra_media_mes", ascending=False).reset_index(drop=True)


def semaforo(pct: float) -> str:
    return "🟢" if pct >= 1 else ("🟡" if pct >= 0.9 else "🔴")


# ----------------------------------------------------------------------------
# Pieza de IA (Gemini) · basada en la plantilla de la ruta A del curso
# ----------------------------------------------------------------------------
MODELO = "gemini-3.8-flash"
MODELO_RESERVA = "gemini-3.5-flash-lite"  # se usa solo si el principal da error 429 (cuota) o 404

SYSTEM_PROMPT = """Eres el asistente de ventas de una PYME. Hablas con un responsable comercial sin perfil técnico.
Usa SOLO las cifras del JSON de DATOS DEL MES; si algo no está en los datos, dilo claramente y no lo inventes.
No recalcules la previsión: ya viene calculada por la app.
Responde en español, con frases cortas y claras, en menos de 180 palabras.
Formatea los importes en euros con punto de miles (12.345 €).
Si te preguntan algo que no tiene que ver con las ventas, di amablemente que solo puedes ayudar con las ventas del mes."""

PROMPT_ANALISIS = """Analiza mi mes. Escribe:
1) Un diagnóstico de una frase (¿llegamos o no al objetivo y por cuánto?).
2) Tres acciones concretas para esta semana que nombren comerciales o clientes reales de los datos.
3) Una frase final de ánimo con un toque de humor."""


def leer_clave() -> str | None:
    """La clave NUNCA va en el código: se guarda en Settings → Secrets de Streamlit Cloud."""
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return os.environ.get("GEMINI_API_KEY")


@st.cache_resource
def obtener_cliente(api_key: str):
    """Crea el cliente de Gemini una sola vez y lo reutiliza entre peticiones."""
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=40_000))


def mensaje_de_error(error: Exception) -> str:
    """Traduce cualquier error de la API a un mensaje claro para el usuario."""
    codigo = getattr(error, "code", None)
    if codigo == 429:
        return "⏳ Se ha agotado la cuota gratuita de la IA por ahora. Prueba de nuevo en un minuto."
    if codigo in (400, 401, 403) and "key" in str(error).lower():
        return "🔑 La clave de la API no es válida. Revisa `GEMINI_API_KEY` en Settings → Secrets."
    if codigo == 404:
        return "🤷 El modelo de IA ya no está disponible. Hay que cambiar la constante MODELO en app.py."
    if codigo and codigo >= 500:
        return "🛠️ El servicio de IA está teniendo problemas ahora mismo. Prueba en unos minutos."
    if codigo:
        return f"⚠️ La IA ha devuelto un error ({codigo}). Prueba otra vez."
    return f"📡 No he podido conectar con la IA ({type(error).__name__}). Revisa la conexión y prueba otra vez."


def preguntar_ia(mensajes: list[dict], datos_json: str, clave: str) -> tuple[bool, str, str]:
    """Envía la conversación a Gemini. Devuelve (ok, texto, modelo usado).
    Si el modelo principal se queda sin cuota, lo intenta con el de reserva."""
    try:
        from google.genai import types
    except ImportError:
        return False, "Falta la librería `google-genai` (revisa requirements.txt).", ""

    # Gemini llama "model" a lo que Streamlit llama "assistant". Enviamos solo los 10 últimos mensajes.
    contenidos = [
        types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
        for m in mensajes[-10:]
    ]
    config = types.GenerateContentConfig(
        system_instruction=f"{SYSTEM_PROMPT}\n\nDATOS DEL MES (JSON):\n{datos_json}", temperature=0.4)

    ultimo_error = None
    for modelo in (MODELO, MODELO_RESERVA):
        try:
            respuesta = obtener_cliente(clave).models.generate_content(
                model=modelo, contents=contenidos, config=config)
            texto = (respuesta.text or "").strip()
            if texto:
                return True, texto, modelo
            return False, "La IA ha devuelto una respuesta vacía. Prueba otra vez.", modelo
        except Exception as error:  # cuota agotada, clave incorrecta, red caída...
            ultimo_error = error
            if getattr(error, "code", None) not in (429, 404):
                break  # otros errores no se arreglan cambiando de modelo
    return False, mensaje_de_error(ultimo_error), ""


def analisis_sin_ia(r: dict) -> str:
    """Plan B basado en reglas: siempre hay algo útil aunque la IA falle."""
    lineas = []
    hueco = r["objetivo"] - r["prevision"]
    if hueco <= 0:
        lineas.append(f"✅ Con el ritmo actual se cerraría en **{eur(r['prevision'])}**, "
                      f"{eur(-hueco)} por encima del objetivo.")
    else:
        lineas.append(f"⚠️ La previsión es **{eur(r['prevision'])}**: faltarían **{eur(hueco)}** para el objetivo. "
                      f"Hay que vender **{eur(r['necesario_por_dia'])}/día** en los {r['dias_laborables_restantes']} días laborables que quedan.")
    rezagados = [c for c in r["comerciales"] if c["pct_objetivo"] < 0.9]
    if rezagados:
        peor = min(rezagados, key=lambda c: c["pct_objetivo"])
        lineas.append(f"- Revisar con **{peor['comercial']}**, que va al {peor['pct_objetivo']:.0%} de su objetivo.")
    if r["clientes_dormidos"]:
        top = r["clientes_dormidos"][:3]
        nombres = ", ".join(f"{c['cliente']} ({eur(c['compra_media_mes'])}/mes)" for c in top)
        lineas.append(f"- Llamar a los clientes dormidos con más potencial: {nombres}.")
    lineas.append("- Priorizar los pedidos de los clientes que más compran para asegurar el cierre.")
    return "\n".join(lineas)


# ----------------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------------
st.title("📊 Previsión de Ventas para Mortales")
st.caption("¿Llegamos al objetivo este mes? Sube tus ventas y lo sabrás en 10 segundos (sin fórmulas de Excel).")

with st.sidebar:
    st.header("1️⃣ Tus datos")
    fichero = st.file_uploader("Sube tu fichero de ventas", type=["csv", "xlsx", "xls"],
                               help="Necesita al menos una columna de fecha y otra de importe. "
                                    "Comercial y cliente son opcionales.")
    usar_ejemplo = st.toggle("Usar datos de ejemplo (distribuidora de gafas)", value=fichero is None,
                             disabled=fichero is not None)

if fichero is None and not usar_ejemplo:
    st.info("👈 Sube un fichero CSV o Excel con tus ventas, o activa los **datos de ejemplo** para probar.")
    st.markdown("**Formato mínimo esperado:**")
    st.dataframe(pd.DataFrame({"fecha": ["15/10/2026", "16/10/2026"], "comercial": ["Laura", "Marc"],
                               "cliente": ["Óptica Sol", "Visión Clara"], "importe": ["1.250,00", "830,50"]}),
                 hide_index=True)
    st.stop()

try:
    if fichero is not None:
        bruto = leer_fichero(fichero.getvalue(), fichero.name)
    else:
        bruto = pd.read_csv(RUTA_EJEMPLO)
    datos, avisos = preparar_datos(bruto)
except ValueError as e:
    st.error(f"😕 {e}")
    st.stop()
except Exception as e:
    st.error(f"😕 No he podido leer el fichero ({type(e).__name__}). "
             "Comprueba que es un CSV o Excel válido y que no está protegido con contraseña.")
    st.stop()

for aviso in avisos:
    st.warning(aviso)

fecha_min, fecha_max = datos["fecha"].min().date(), datos["fecha"].max().date()

with st.sidebar:
    st.header("2️⃣ El mes")
    corte = st.date_input("Fecha de corte (\"hoy\")", value=fecha_max, min_value=fecha_min,
                          max_value=fin_de_mes(fecha_max), format="DD/MM/YYYY",
                          help="Por defecto, el último día con datos.")
    comerciales_lista = sorted(datos["comercial"].unique())
    filtro = st.selectbox("Comercial", ["Todo el equipo"] + [c for c in comerciales_lista if c != "Todo el equipo"])
    datos_vista = datos if filtro == "Todo el equipo" else datos[datos["comercial"] == filtro]
    objetivo = st.number_input("🎯 Objetivo del mes (€)", min_value=0.0, step=1000.0, format="%.0f",
                               value=objetivo_sugerido(datos_vista, corte),
                               key=f"obj_{filtro}_{corte:%Y%m}",
                               help="Sugerencia: mismo mes del año pasado +10 %. Cámbialo por el vuestro.")

if objetivo <= 0:
    st.error("🎯 Pon un objetivo mayor que 0 € para poder calcular la previsión.")
    st.stop()
if corte > fecha_max:
    st.warning(f"No hay ventas después del {fecha_max:%d/%m/%Y}: los días posteriores cuentan como 0 €.")

p = prever_cierre(datos_vista, corte)
pct = p["prevision"] / objetivo
falta = max(objetivo - p["vendido"], 0)
necesario_dia = falta / p["dias_restantes"] if p["dias_restantes"] else 0

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
st.subheader(f"{filtro} · {MESES[corte.month - 1].capitalize()} {corte.year} (datos hasta el {corte:%d/%m/%Y})")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vendido hasta hoy", eur(p["vendido"]), f"{p['vendido'] / objetivo:.0%} del objetivo", delta_color="off")
c2.metric("Previsión de cierre", eur(p["prevision"]), f"{pct - 1:+.0%} vs objetivo")
c3.metric("Objetivo", eur(objetivo))
c4.metric("Necesario por día laborable", eur(necesario_dia) if falta else "¡Conseguido! 🎉",
          f"{p['dias_restantes']} días laborables restantes", delta_color="off")

# Celebraciones y avisos
clave_fiesta = f"fiesta_{filtro}_{corte}_{objetivo}"
if p["vendido"] >= objetivo:
    st.success("🏆 **¡Objetivo conseguido!** Ya se puede pedir la pizza del viernes.")
    if not st.session_state.get(clave_fiesta):
        st.balloons()
        st.session_state[clave_fiesta] = True
elif pct >= 1:
    st.success(f"🚀 **Vais camino del objetivo.** Si se mantiene el ritmo, cerraréis en {eur(p['prevision'])}.")
    if not st.session_state.get(clave_fiesta):
        st.balloons()
        st.session_state[clave_fiesta] = True
elif pct >= 0.9:
    st.warning(f"😬 **Muy justito.** Faltan {eur(objetivo - p['prevision'])} sobre la previsión: un empujón y está.")
else:
    st.error(f"🧯 **Alerta roja.** Al ritmo actual faltarán unos {eur(objetivo - p['prevision'])}. "
             f"Toca vender {eur(necesario_dia)} cada día laborable.")

col_termo, col_graf = st.columns([1, 2])
with col_termo:
    termo = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct * 100,
        number={"suffix": "%", "valueformat": ".0f"},
        title={"text": "Termómetro: previsión vs objetivo"},
        gauge={
            "axis": {"range": [0, max(130, pct * 100 + 10)]},
            "bar": {"color": "#2E7D32" if pct >= 1 else ("#F9A825" if pct >= 0.9 else "#C62828")},
            "steps": [{"range": [0, p["vendido"] / objetivo * 100], "color": "#BBDEFB"}],
            "threshold": {"line": {"color": "black", "width": 4}, "value": 100},
        },
    ))
    termo.update_layout(height=300, margin=dict(l=20, r=20, t=60, b=10))
    st.plotly_chart(termo, width="stretch")
    st.caption("Azul claro: lo ya vendido. Barra: la previsión. Línea negra: el objetivo.")

with col_graf:
    mes = datos_vista[(datos_vista["fecha"] >= pd.Timestamp(p["inicio"])) & (datos_vista["fecha"] <= pd.Timestamp(corte))]
    dias = pd.date_range(p["inicio"], corte)
    acumulado = mes.groupby("fecha")["importe"].sum().reindex(dias, fill_value=0).cumsum()
    ini_ant = pd.Timestamp(p["inicio"]) - pd.DateOffset(months=1)
    ant = datos_vista[(datos_vista["fecha"] >= ini_ant) & (datos_vista["fecha"] < pd.Timestamp(p["inicio"]))]
    dias_ant = pd.date_range(ini_ant, pd.Timestamp(p["inicio"]) - pd.Timedelta(days=1))
    acum_ant = ant.groupby("fecha")["importe"].sum().reindex(dias_ant, fill_value=0).cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[d.day for d in dias_ant], y=acum_ant.values, name="Mes anterior",
                             line=dict(color="#B0BEC5", width=2)))
    fig.add_trace(go.Scatter(x=[d.day for d in dias], y=acumulado.values, name="Real", line=dict(color="#1565C0", width=4)))
    if p["fin"] > corte:
        fig.add_trace(go.Scatter(x=[corte.day, p["fin"].day], y=[p["vendido"], p["prevision"]], name="Previsión",
                                 line=dict(color="#1565C0", width=3, dash="dash")))
        fig.add_trace(go.Scatter(x=[corte.day, p["fin"].day, p["fin"].day, corte.day],
                                 y=[p["vendido"], p["alto"], p["bajo"], p["vendido"]], fill="toself",
                                 fillcolor="rgba(21,101,192,0.12)", line=dict(width=0), mode="lines", name="Rango", hoverinfo="skip"))
    fig.add_hline(y=objetivo, line_dash="dot", line_color="#C62828", annotation_text=f"Objetivo {eur(objetivo)}")
    fig.update_layout(title="Ventas acumuladas del mes", xaxis_title="Día del mes", yaxis_title="€",
                      height=340, margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.25),
                      separators=",.")
    st.plotly_chart(fig, width="stretch")

# Por comercial
filas_com = []
inicio_ts = pd.Timestamp(p["inicio"])
previos3 = datos[(datos["fecha"] >= inicio_ts - pd.DateOffset(months=3)) & (datos["fecha"] < inicio_ts)]
peso_total = previos3["importe"].sum()
for com in comerciales_lista:
    sub = datos[datos["comercial"] == com]
    pc = prever_cierre(sub, corte)
    peso = previos3.loc[previos3["comercial"] == com, "importe"].sum() / peso_total if peso_total else 1 / len(comerciales_lista)
    obj_c = objetivo * peso if filtro == "Todo el equipo" else (objetivo if com == filtro else np.nan)
    if filtro != "Todo el equipo" and com != filtro:
        continue
    pct_c = pc["prevision"] / obj_c if obj_c else 0
    filas_com.append({"comercial": com, "vendido": pc["vendido"], "prevision": pc["prevision"],
                      "objetivo": obj_c, "pct_objetivo": pct_c})

tab_com, tab_dorm, tab_metodo = st.tabs(["👥 Por comercial", "😴 Clientes dormidos", "🔍 ¿Cómo se calcula?"])
with tab_com:
    if filtro == "Todo el equipo":
        st.caption("El objetivo de cada comercial es su peso en las ventas de los últimos 3 meses.")
    tabla = pd.DataFrame(filas_com)
    tabla.insert(0, "", tabla["pct_objetivo"].apply(semaforo))
    tabla["pct_objetivo"] = tabla["pct_objetivo"] * 100
    st.dataframe(
        tabla.rename(columns={"comercial": "Comercial", "vendido": "Vendido", "prevision": "Previsión",
                              "objetivo": "Objetivo", "pct_objetivo": "% previsto"}),
        hide_index=True, width="stretch",
        column_config={
            "Vendido": st.column_config.NumberColumn(format="%.0f €"),
            "Previsión": st.column_config.NumberColumn(format="%.0f €"),
            "Objetivo": st.column_config.NumberColumn(format="%.0f €"),
            "% previsto": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=130),
        },
    )

dormidos = clientes_dormidos(datos_vista, corte)
with tab_dorm:
    st.caption("Clientes que compraron en **cada uno** de los 3 meses anteriores y este mes todavía no. Una llamada a tiempo…")
    if dormidos.empty:
        st.info("No hay clientes dormidos (o el fichero no tiene columna de cliente). ¡Buena señal!")
    else:
        st.dataframe(dormidos.rename(columns={"cliente": "Cliente", "comercial": "Comercial",
                                              "compra_media_mes": "Compra media/mes", "ultima_compra": "Última compra"}),
                     hide_index=True, width="stretch",
                     column_config={"Compra media/mes": st.column_config.NumberColumn(format="%.0f €"),
                                    "Última compra": st.column_config.DateColumn(format="DD/MM/YYYY")})
        st.caption(f"Potencial si todos compran como siempre: **{eur(dormidos['compra_media_mes'].sum())}**")

with tab_metodo:
    st.markdown(f"""
- **Ritmo actual:** {eur(p['vendido'])} en {p['dias_transcurridos']} días laborables → × {p['dias_totales']} días del mes = **{eur(p['prev_ritmo'])}**
- **Patrón histórico:** en los últimos {p['meses_historicos']} meses, a estas alturas se llevaba vendida una parte del mes; dividiendo lo vendido entre esa parte = **{eur(p['prev_hist'])}**
- **Previsión:** {p['metodo']} → **{eur(p['prevision'])}** (rango {eur(p['bajo'])} – {eur(p['alto'])})
- **Objetivo sugerido:** mismo mes del año pasado +10 % (o media de 3 meses +5 % si no hay histórico).

La IA **no** hace estos cálculos: solo los explica y propone acciones. Así los números nunca son inventados.
""")

# Asistente IA (chat con memoria, como la plantilla del curso)
st.divider()
st.subheader("🤖 Tu asistente de ventas")

resumen = {
    "ambito": filtro,
    "mes": f"{corte:%m/%Y}",
    "fecha_corte": f"{corte:%d/%m/%Y}",
    "objetivo": round(objetivo),
    "vendido": round(p["vendido"]),
    "prevision": round(p["prevision"]),
    "rango_prevision": [round(p["bajo"]), round(p["alto"])],
    "dias_laborables_restantes": p["dias_restantes"],
    "necesario_por_dia": round(necesario_dia),
    "comerciales": [{**c, "vendido": round(c["vendido"]), "prevision": round(c["prevision"]),
                     "objetivo": round(c["objetivo"]) if pd.notna(c["objetivo"]) else None,
                     "pct_objetivo": round(c["pct_objetivo"], 2)} for c in filas_com],
    "clientes_dormidos": [] if dormidos.empty else [
        {"cliente": r.cliente, "comercial": r.comercial, "compra_media_mes": round(r.compra_media_mes)}
        for r in dormidos.head(8).itertuples()],
    "ventas_ultimos_meses": {str(k): round(v) for k, v in datos_vista[datos_vista["fecha"] < pd.Timestamp(p["inicio"])]
                             .groupby(datos_vista["fecha"].dt.to_period("M"))["importe"].sum().tail(12).items()},
}
if "cliente" in datos_vista and datos_vista["cliente"].notna().any():
    top = mes.groupby("cliente")["importe"].sum().nlargest(5)
    resumen["top_clientes_mes"] = {k: round(v) for k, v in top.items()}

datos_json = json.dumps(resumen, ensure_ascii=False, default=str)
reglas = {**resumen, "objetivo": objetivo, "prevision": p["prevision"], "necesario_por_dia": necesario_dia}
clave = leer_clave()

# Si cambian los datos, el filtro, la fecha o el objetivo, la conversación empieza de cero
contexto = f"{fichero.name if fichero else 'ejemplo'}|{filtro}|{corte}|{objetivo}"
if st.session_state.get("contexto_chat") != contexto:
    st.session_state.contexto_chat = contexto
    st.session_state.mensajes = []

if not clave:
    st.info("ℹ️ Modo sin IA: no hay clave `GEMINI_API_KEY` configurada. Te muestro un análisis automático basado en reglas.")

col_a, col_b = st.columns([1, 1])
analizar = col_a.button("✨ Analiza mi mes", type="primary", width="stretch")
if col_b.button("🧹 Borrar conversación", width="stretch"):
    st.session_state.mensajes = []

for m in st.session_state.mensajes:
    with st.chat_message(m["role"]):
        st.markdown(m.get("mostrar", m["content"]))

pregunta = st.chat_input("Pregúntale a tu asistente, por ejemplo: ¿quién va peor y a qué clientes llamo?")
if analizar:
    nuevo = {"role": "user", "content": PROMPT_ANALISIS, "mostrar": "✨ Analiza mi mes"}
elif pregunta and pregunta.strip():
    nuevo = {"role": "user", "content": pregunta.strip()}
else:
    nuevo = None

if nuevo:
    st.session_state.mensajes.append(nuevo)
    with st.chat_message("user"):
        st.markdown(nuevo.get("mostrar", nuevo["content"]))
    with st.chat_message("assistant"):
        if clave:
            with st.spinner("Pensando como un director comercial con café… ☕"):
                ok, texto, modelo_usado = preguntar_ia(st.session_state.mensajes, datos_json, clave)
        else:
            ok, texto, modelo_usado = False, "", ""
        if ok:
            st.markdown(texto)
            st.caption(f"Generado con IA ({modelo_usado}) a partir del resumen del mes. Revísalo antes de decidir.")
        else:
            aviso = texto or "🔌 Modo sin IA: no hay clave configurada, así que no puedo responder preguntas libres."
            texto = f"{aviso}\n\nMientras tanto, aquí tienes el análisis automático:\n\n{analisis_sin_ia(reglas)}"
            st.markdown(texto)
    st.session_state.mensajes.append({"role": "assistant", "content": texto})

with st.expander("Ver los datos que recibe la IA"):
    st.caption("La IA solo recibe este resumen, nunca tu fichero completo.")
    st.json(resumen)
