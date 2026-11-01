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
import plotly.express as px
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


def preguntar_ia(mensajes: list[dict], datos_json: str, clave: str, estilo: str = "") -> tuple[bool, str, str]:
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
        system_instruction=f"{SYSTEM_PROMPT}\n{estilo}\n\nDATOS DEL MES (JSON):\n{datos_json}", temperature=0.6)

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
# Extras: diseño, personalidades, mensajes a clientes e informe descargable
# ----------------------------------------------------------------------------
ESTILO_CSS = """
<style>
.hero {background: linear-gradient(120deg, #4338CA 0%, #7C3AED 55%, #DB2777 100%);
       padding: 1.4rem 1.8rem; border-radius: 18px; color: white; margin-bottom: 1rem;
       box-shadow: 0 8px 24px rgba(67,56,202,.25);}
.hero h1 {color: white; margin: 0; font-size: 2.1rem;}
.hero p {color: rgba(255,255,255,.88); margin: .3rem 0 0 0; font-size: 1.05rem;}
.tarjeta {background: white; border-radius: 16px; padding: 1rem 1.2rem; border: 1px solid #EEF0F6;
          box-shadow: 0 4px 14px rgba(30,41,59,.06); border-top: 5px solid var(--color); height: 100%;}
.tarjeta .t {font-size: .85rem; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: .03em;}
.tarjeta .v {font-size: 1.9rem; font-weight: 800; color: #0F172A; margin: .15rem 0;}
.tarjeta .s {font-size: .88rem; color: var(--color); font-weight: 600;}
div[data-testid="stTabs"] button p {font-size: 1rem;}
</style>
"""

PERSONALIDADES = {
    "🎩 Director serio": "Tono: director comercial serio y directo, sin rodeos ni bromas, muy concreto.",
    "💪 Coach motivador": "Tono: coach motivador y positivo, con energía, celebra lo bueno y anima a mejorar lo malo.",
    "⚽ Locutor de fútbol": ("Tono: locutor de fútbol emocionado retransmitiendo el mes como un partido "
                           "(los comerciales son jugadores, el objetivo es la portería, los días que quedan son los minutos). "
                           "Exagera con gracia, pero las cifras deben ser exactas."),
}

PREGUNTAS_SUGERIDAS = [
    "¿Llegamos al objetivo?",
    "¿Quién va peor y por qué?",
    "¿A qué clientes llamo primero?",
    "Compárame con los meses anteriores",
]

PROMPT_MENSAJE = """Escribe un {canal} para reactivar a un cliente que suele comprar cada mes y este mes todavía no ha hecho pedido.
- Cliente: {cliente}
- Lo firma: {comercial} (su comercial)
- Compra media mensual: {media}
- Última compra: {ultima}
Requisitos: en español, cercano y profesional, sin sonar desesperado; menciona que hace tiempo que no hablamos,
ofrece ayuda (novedades, reposición de stock o una visita) y termina con una pregunta fácil de contestar.
{extension} Devuelve SOLO el texto del mensaje{asunto}, sin explicaciones."""


def tarjeta(titulo: str, valor: str, sub: str = "", color: str = "#4338CA") -> str:
    return (f'<div class="tarjeta" style="--color:{color}"><div class="t">{titulo}</div>'
            f'<div class="v">{valor}</div><div class="s">{sub}</div></div>')


def mensaje_cliente_sin_ia(cliente: str, comercial: str, canal: str) -> str:
    """Plantilla fija por si la IA no está disponible."""
    nombre = comercial.split()[0]
    if canal == "WhatsApp":
        return (f"¡Hola! Soy {nombre}, de vuestro proveedor 😊 Hace unas semanas que no hablamos y quería saber "
                f"qué tal va todo en {cliente}. ¿Os hace falta reponer algo o que os pase las novedades de este mes?")
    return (f"Asunto: ¿Qué tal todo por {cliente}?\n\nHola:\n\nHace unas semanas que no hablamos y quería saber "
            f"cómo va la temporada. Tenemos novedades este mes y, si os viene bien, puedo pasarme a enseñároslas "
            f"o preparar una reposición de lo que más os funciona.\n\n¿Te viene bien que te llame esta semana?\n\n"
            f"Un saludo,\n{comercial}")


def crear_informe(resumen: dict, tabla_com: pd.DataFrame, dormidos: pd.DataFrame, analisis: str) -> bytes:
    """Excel con el resumen del mes para enviar al equipo."""
    import io
    from openpyxl.styles import Font, PatternFill
    buf = io.BytesIO()
    filas = [
        ("Ámbito", resumen["ambito"]), ("Mes", resumen["mes"]), ("Datos hasta", resumen["fecha_corte"]),
        ("Objetivo (€)", resumen["objetivo"]), ("Vendido (€)", resumen["vendido"]),
        ("Previsión de cierre (€)", resumen["prevision"]),
        ("Rango de previsión (€)", f"{resumen['rango_prevision'][0]} – {resumen['rango_prevision'][1]}"),
        ("% previsto sobre objetivo", round(resumen["prevision"] / resumen["objetivo"], 3) if resumen["objetivo"] else None),
        ("Días laborables restantes", resumen["dias_laborables_restantes"]),
        ("Necesario por día laborable (€)", resumen["necesario_por_dia"]),
    ]
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(filas, columns=["Indicador", "Valor"]).to_excel(xw, sheet_name="Resumen", index=False)
        tabla_com.to_excel(xw, sheet_name="Por comercial", index=False)
        (dormidos if not dormidos.empty else pd.DataFrame({"Info": ["No hay clientes dormidos"]})).to_excel(
            xw, sheet_name="Clientes dormidos", index=False)
        pd.DataFrame({"Análisis": (analisis or "Pulsa «Analiza mi mes» en la app para incluir aquí el análisis.").split("\n")}
                     ).to_excel(xw, sheet_name="Análisis", index=False)
        for hoja in xw.book.worksheets:
            for celda in hoja[1]:
                celda.font = Font(bold=True, color="FFFFFF")
                celda.fill = PatternFill("solid", fgColor="4338CA")
            for col in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in col)
                hoja.column_dimensions[col[0].column_letter].width = min(max(12, ancho + 2), 90)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Interfaz
# ----------------------------------------------------------------------------
st.markdown(ESTILO_CSS, unsafe_allow_html=True)
st.markdown("""<div class="hero"><h1>📊 Previsión de Ventas para Mortales</h1>
<p>¿Llegamos al objetivo este mes? Sube tus ventas y lo sabrás en 10 segundos (sin fórmulas de Excel).</p></div>""",
            unsafe_allow_html=True)

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
        if not RUTA_EJEMPLO.exists():
            st.error("😕 No encuentro los datos de ejemplo (`data/ventas_ejemplo.csv`). "
                     "Si eres quien mantiene la app: sube la carpeta `data` al repositorio de GitHub. "
                     "Si eres usuario: desactiva los datos de ejemplo y sube tu propio fichero.")
            st.stop()
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


# ----------------------------------------------------------------------------
# Cálculos del mes
# ----------------------------------------------------------------------------
p = prever_cierre(datos_vista, corte)
pct = p["prevision"] / objetivo
falta = max(objetivo - p["vendido"], 0)
necesario_dia = falta / p["dias_restantes"] if p["dias_restantes"] else 0
inicio_ts = pd.Timestamp(p["inicio"])
mes = datos_vista[(datos_vista["fecha"] >= inicio_ts) & (datos_vista["fecha"] <= pd.Timestamp(corte))]

# Por comercial: su objetivo es su peso en las ventas de los últimos 3 meses
filas_com = []
previos3 = datos[(datos["fecha"] >= inicio_ts - pd.DateOffset(months=3)) & (datos["fecha"] < inicio_ts)]
peso_total = previos3["importe"].sum()
for com in comerciales_lista:
    if filtro != "Todo el equipo" and com != filtro:
        continue
    pc = prever_cierre(datos[datos["comercial"] == com], corte)
    if filtro == "Todo el equipo":
        peso = (previos3.loc[previos3["comercial"] == com, "importe"].sum() / peso_total
                if peso_total else 1 / len(comerciales_lista))
        obj_c = objetivo * peso
    else:
        obj_c = objetivo
    filas_com.append({"comercial": com, "vendido": pc["vendido"], "prevision": pc["prevision"],
                      "objetivo": obj_c, "pct_objetivo": pc["prevision"] / obj_c if obj_c else 0})
tabla_com = pd.DataFrame(filas_com)
dormidos = clientes_dormidos(datos_vista, corte)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
st.subheader(f"{filtro} · {MESES[corte.month - 1].capitalize()} {corte.year} (datos hasta el {corte:%d/%m/%Y})")

color_estado = "#16A34A" if pct >= 1 else ("#D97706" if pct >= 0.9 else "#DC2626")
c1, c2, c3, c4 = st.columns(4)
c1.markdown(tarjeta("Vendido hasta hoy", eur(p["vendido"]), f"{p['vendido'] / objetivo:.0%} del objetivo", "#4338CA"),
            unsafe_allow_html=True)
c2.markdown(tarjeta("Previsión de cierre", eur(p["prevision"]), f"{pct - 1:+.0%} vs objetivo", color_estado),
            unsafe_allow_html=True)
c3.markdown(tarjeta("Objetivo", eur(objetivo), f"{p['dias_totales']} días laborables este mes", "#7C3AED"),
            unsafe_allow_html=True)
c4.markdown(tarjeta("Necesario por día", eur(necesario_dia) if falta else "¡Hecho! 🎉",
                    f"{p['dias_restantes']} días laborables restantes", "#DB2777"), unsafe_allow_html=True)
st.write("")

# Celebraciones y avisos
clave_fiesta = f"fiesta_{filtro}_{corte}_{objetivo}"
if p["vendido"] >= objetivo:
    st.success("🏆 **¡Objetivo conseguido!** Ya se puede pedir la pizza del viernes.")
elif pct >= 1:
    st.success(f"🚀 **Vais camino del objetivo.** Si se mantiene el ritmo, cerraréis en {eur(p['prevision'])}.")
elif pct >= 0.9:
    st.warning(f"😬 **Muy justito.** Faltan {eur(objetivo - p['prevision'])} sobre la previsión: un empujón y está.")
else:
    st.error(f"🧯 **Alerta roja.** Al ritmo actual faltarán unos {eur(objetivo - p['prevision'])}. "
             f"Toca vender {eur(necesario_dia)} cada día laborable.")
if pct >= 1 and not st.session_state.get(clave_fiesta):
    st.balloons()
    st.session_state[clave_fiesta] = True


def dibujar_termometro(valor_pct: float, vendido_pct: float, titulo: str, alto: int = 300) -> go.Figure:
    color = "#16A34A" if valor_pct >= 100 else ("#D97706" if valor_pct >= 90 else "#DC2626")
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=valor_pct,
        number={"suffix": "%", "valueformat": ".0f", "font": {"size": 46}},
        title={"text": titulo},
        gauge={"axis": {"range": [0, max(130, valor_pct + 10)]}, "bar": {"color": color, "thickness": 0.75},
               "steps": [{"range": [0, vendido_pct], "color": "#C7D2FE"}],
               "threshold": {"line": {"color": "#0F172A", "width": 4}, "value": 100}},
    ))
    fig.update_layout(height=alto, margin=dict(l=20, r=20, t=60, b=10))
    return fig


col_termo, col_graf = st.columns([1, 2])
with col_termo:
    st.plotly_chart(dibujar_termometro(pct * 100, p["vendido"] / objetivo * 100, "Previsión vs objetivo"),
                    width="stretch")
    st.caption("Lila claro: lo ya vendido. Barra: la previsión. Línea negra: el objetivo.")

with col_graf:
    dias = pd.date_range(p["inicio"], corte)
    acumulado = mes.groupby("fecha")["importe"].sum().reindex(dias, fill_value=0).cumsum()
    ini_ant = inicio_ts - pd.DateOffset(months=1)
    ant = datos_vista[(datos_vista["fecha"] >= ini_ant) & (datos_vista["fecha"] < inicio_ts)]
    dias_ant = pd.date_range(ini_ant, inicio_ts - pd.Timedelta(days=1))
    acum_ant = ant.groupby("fecha")["importe"].sum().reindex(dias_ant, fill_value=0).cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[d.day for d in dias_ant], y=acum_ant.values, name="Mes anterior",
                             line=dict(color="#CBD5E1", width=2)))
    fig.add_trace(go.Scatter(x=[d.day for d in dias], y=acumulado.values, name="Real",
                             line=dict(color="#4338CA", width=4), fill="tozeroy", fillcolor="rgba(67,56,202,0.08)"))
    if p["fin"] > corte:
        fig.add_trace(go.Scatter(x=[corte.day, p["fin"].day, p["fin"].day, corte.day],
                                 y=[p["vendido"], p["alto"], p["bajo"], p["vendido"]], fill="toself",
                                 fillcolor="rgba(124,58,237,0.12)", line=dict(width=0), mode="lines",
                                 name="Rango", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[corte.day, p["fin"].day], y=[p["vendido"], p["prevision"]], name="Previsión",
                                 line=dict(color="#7C3AED", width=3, dash="dash")))
    fig.add_hline(y=objetivo, line_dash="dot", line_color="#DB2777", annotation_text=f"Objetivo {eur(objetivo)}")
    fig.update_layout(title="Ventas acumuladas del mes", xaxis_title="Día del mes", yaxis_title="€",
                      height=340, margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.25),
                      separators=",.", plot_bgcolor="white")
    fig.update_yaxes(gridcolor="#EEF0F6")
    st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------------
# Pestañas
# ----------------------------------------------------------------------------
# Usamos un selector en vez de st.tabs para que la pestaña elegida no se pierda al pulsar un botón
SECCIONES = ["👥 Por comercial", "🏁 Carrera", "🎚️ ¿Y si…?", "😴 Clientes dormidos", "🔍 ¿Cómo se calcula?"]
seccion = st.segmented_control("Sección", SECCIONES, default=SECCIONES[0], key="seccion",
                               label_visibility="collapsed") or SECCIONES[0]

if seccion == SECCIONES[0]:
    if filtro == "Todo el equipo":
        st.caption("El objetivo de cada comercial es su peso en las ventas de los últimos 3 meses.")
    tabla = tabla_com.copy()
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

if seccion == SECCIONES[1]:
    if filtro != "Todo el equipo" or len(filas_com) < 2:
        st.info("🏁 La carrera necesita al menos dos comerciales: elige **Todo el equipo** en la barra lateral (y un fichero con columna de comercial).")
    else:
        st.caption("Pulsa ▶️ y mira cómo avanza cada comercial hacia **su** objetivo (la meta es el 100 %).")
        dias_lab = pd.bdate_range(p["inicio"], corte)
        if len(dias_lab) == 0:
            st.info("Todavía no ha pasado ningún día laborable este mes: la carrera aún no ha empezado.")
        else:
            objetivos_c = {f["comercial"]: f["objetivo"] for f in filas_com}
            mes_todos = datos[(datos["fecha"] >= inicio_ts) & (datos["fecha"] <= pd.Timestamp(corte))]
            diario = (mes_todos.groupby(["fecha", "comercial"])["importe"].sum().unstack(fill_value=0)
                      .reindex(pd.date_range(p["inicio"], corte), fill_value=0)
                      .reindex(columns=list(objetivos_c), fill_value=0).cumsum())
            filas_carrera = []
            for d in dias_lab:
                for com, obj_c in objetivos_c.items():
                    filas_carrera.append({"Día": f"{d:%d/%m}", "Comercial": com,
                                          "% del objetivo": diario.loc[d, com] / obj_c * 100 if obj_c else 0,
                                          "Vendido": eur(diario.loc[d, com])})
            carrera = pd.DataFrame(filas_carrera)
            tope = max(110, carrera["% del objetivo"].max() * 1.1)
            fig_c = px.bar(carrera, x="% del objetivo", y="Comercial", color="Comercial", orientation="h",
                           animation_frame="Día", range_x=[0, tope], text="Vendido",
                           color_discrete_sequence=["#4338CA", "#7C3AED", "#DB2777", "#0EA5E9", "#16A34A", "#D97706"])
            fig_c.add_vline(x=100, line_dash="dash", line_color="#0F172A", annotation_text="🏁 Meta")
            fig_c.update_layout(height=380, showlegend=False, plot_bgcolor="white",
                                margin=dict(l=10, r=10, t=30, b=10))
            fig_c.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 350
            fig_c.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] = 250
            st.plotly_chart(fig_c, width="stretch")
            lider = max(filas_com, key=lambda f: f["vendido"] / f["objetivo"] if f["objetivo"] else 0)
            st.markdown(f"🥇 Va en cabeza **{lider['comercial']}**, con el "
                        f"{lider['vendido'] / lider['objetivo']:.0%} de su objetivo ya vendido.")

if seccion == SECCIONES[2]:
    st.caption("Juega con los escenarios y mira si llegáis. Nada de esto cambia tus datos.")
    s1, s2 = st.columns([3, 2])
    with s1:
        if dormidos.empty:
            n_rec = 0
            st.info("No hay clientes dormidos que recuperar en este mes.")
        else:
            n_rec = st.slider("😴 Clientes dormidos que recupero", 0, len(dormidos), 0,
                              help="Se cuentan primero los que más compran. Suman su compra media mensual.")
        extra_ritmo = st.slider("⚡ Cambio del ritmo de ventas en lo que queda de mes", -50, 100, 0, step=5,
                                format="%d%%")
        pedido_extra = st.number_input("📦 Pedido grande extra (€)", min_value=0.0, step=500.0, format="%.0f")
    recuperado = float(dormidos["compra_media_mes"].head(n_rec).sum()) if n_rec else 0.0
    pendiente = p["prevision"] - p["vendido"]
    prev_sim = p["vendido"] + pendiente * (1 + extra_ritmo / 100) + recuperado + pedido_extra
    pct_sim = prev_sim / objetivo
    with s2:
        st.plotly_chart(dibujar_termometro(pct_sim * 100, p["vendido"] / objetivo * 100, "Escenario simulado", 260),
                        width="stretch")
    st.markdown(f"**Previsión simulada: {eur(prev_sim)}** ({pct_sim - 1:+.0%} vs objetivo) · "
                f"{eur(prev_sim - p['prevision'])} más que la previsión actual.")
    if n_rec:
        st.caption("Recuperados: " + ", ".join(dormidos["cliente"].head(n_rec)))
    clave_sim = f"sim_{n_rec}_{extra_ritmo}_{pedido_extra}_{objetivo}"
    if pct_sim >= 1 > pct:
        st.success("🎉 **¡Con este escenario llegáis al objetivo!** Ya tenéis plan.")
        if st.session_state.get("ultimo_sim_globos") != clave_sim:
            st.balloons()
            st.session_state.ultimo_sim_globos = clave_sim
    elif pct_sim < 1:
        st.warning(f"Aún faltarían {eur(objetivo - prev_sim)}. Prueba a recuperar más clientes o a subir el ritmo.")

if seccion == SECCIONES[3]:
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

        st.markdown("#### ✉️ Despierta a un cliente")
        m1, m2 = st.columns([2, 1])
        cliente_sel = m1.selectbox("Cliente", dormidos["cliente"].tolist())
        canal = m2.radio("Canal", ["Email", "WhatsApp"], horizontal=True)
        fila = dormidos[dormidos["cliente"] == cliente_sel].iloc[0]
        if st.button("✍️ Escríbeme el mensaje", type="primary"):
            prompt_msg = PROMPT_MENSAJE.format(
                canal="email" if canal == "Email" else "mensaje de WhatsApp", cliente=cliente_sel,
                comercial=fila["comercial"], media=eur(fila["compra_media_mes"]),
                ultima=f"{fila['ultima_compra']:%d/%m/%Y}",
                extension="Máximo 120 palabras." if canal == "Email" else "Máximo 50 palabras y un emoji como mucho.",
                asunto=" (empieza con una línea 'Asunto: …')" if canal == "Email" else "")
            clave_tmp = leer_clave()
            ok_m, texto_m = False, ""
            if clave_tmp:
                with st.spinner("Afinando la pluma… 🖋️"):
                    ok_m, texto_m, _ = preguntar_ia([{"role": "user", "content": prompt_msg}], "{}", clave_tmp)
            if not ok_m:
                aviso_m = texto_m or "🔌 Modo sin IA: te dejo una plantilla estándar."
                texto_m = mensaje_cliente_sin_ia(cliente_sel, fila["comercial"], canal)
                st.session_state.aviso_mensaje = aviso_m
            else:
                st.session_state.aviso_mensaje = ""
            st.session_state.mensaje_cliente = (cliente_sel, canal, texto_m)
        guardado = st.session_state.get("mensaje_cliente")
        if guardado and guardado[0] == cliente_sel and guardado[1] == canal:
            if st.session_state.get("aviso_mensaje"):
                st.warning(st.session_state.aviso_mensaje)
            st.code(guardado[2], language=None, wrap_lines=True)
            st.caption("Copia el mensaje con el icono de la esquina superior derecha y revísalo antes de enviarlo.")

if seccion == SECCIONES[4]:
    st.markdown(f"""
- **Ritmo actual:** {eur(p['vendido'])} en {p['dias_transcurridos']} días laborables → × {p['dias_totales']} días del mes = **{eur(p['prev_ritmo'])}**
- **Patrón histórico:** en los últimos {p['meses_historicos']} meses, a estas alturas se llevaba vendida una parte del mes; dividiendo lo vendido entre esa parte = **{eur(p['prev_hist'])}**
- **Previsión:** {p['metodo']} → **{eur(p['prevision'])}** (rango {eur(p['bajo'])} – {eur(p['alto'])})
- **Objetivo sugerido:** mismo mes del año pasado +10 % (o media de 3 meses +5 % si no hay histórico).

La IA **no** hace estos cálculos: solo los explica, propone acciones y redacta mensajes. Así los números nunca son inventados.
""")

# ----------------------------------------------------------------------------
# Asistente IA (chat con memoria, como la plantilla del curso)
# ----------------------------------------------------------------------------
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
                     "objetivo": round(c["objetivo"]), "pct_objetivo": round(c["pct_objetivo"], 2)}
                    for c in filas_com],
    "clientes_dormidos": [] if dormidos.empty else [
        {"cliente": r.cliente, "comercial": r.comercial, "compra_media_mes": round(r.compra_media_mes)}
        for r in dormidos.head(8).itertuples()],
    "ventas_ultimos_meses": {str(k): round(v) for k, v in datos_vista[datos_vista["fecha"] < inicio_ts]
                             .groupby(datos_vista["fecha"].dt.to_period("M"))["importe"].sum().tail(12).items()},
}
if datos_vista["cliente"].notna().any():
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
    st.session_state.ultimo_analisis = ""

if not clave:
    st.info("ℹ️ Modo sin IA: no hay clave `GEMINI_API_KEY` configurada. Te muestro un análisis automático basado en reglas.")

personalidad = st.radio("Personalidad del asistente", list(PERSONALIDADES), horizontal=True)
col_a, col_b = st.columns([1, 1])
analizar = col_a.button("✨ Analiza mi mes", type="primary", width="stretch")
if col_b.button("🧹 Borrar conversación", width="stretch"):
    st.session_state.mensajes = []

st.caption("¿No sabes qué preguntar? Prueba con una de estas:")
sugerida = None
for col, texto_p in zip(st.columns(len(PREGUNTAS_SUGERIDAS)), PREGUNTAS_SUGERIDAS):
    if col.button(texto_p, width="stretch"):
        sugerida = texto_p

for m in st.session_state.mensajes:
    with st.chat_message(m["role"]):
        st.markdown(m.get("mostrar", m["content"]))

pregunta = st.chat_input("Pregúntale a tu asistente, por ejemplo: ¿quién va peor y a qué clientes llamo?")
if analizar:
    nuevo = {"role": "user", "content": PROMPT_ANALISIS, "mostrar": f"✨ Analiza mi mes ({personalidad})"}
elif sugerida:
    nuevo = {"role": "user", "content": sugerida}
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
                ok, texto, modelo_usado = preguntar_ia(st.session_state.mensajes, datos_json, clave,
                                                       PERSONALIDADES[personalidad])
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
    if analizar:
        st.session_state.ultimo_analisis = texto

with st.expander("Ver los datos que recibe la IA"):
    st.caption("La IA solo recibe este resumen, nunca tu fichero completo.")
    st.json(resumen)

# ----------------------------------------------------------------------------
# Informe descargable (en la barra lateral)
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("3️⃣ Informe del lunes")
    analisis_informe = st.session_state.get("ultimo_analisis") or analisis_sin_ia(reglas)
    tabla_informe = tabla_com.rename(columns={"comercial": "Comercial", "vendido": "Vendido (€)",
                                              "prevision": "Previsión (€)", "objetivo": "Objetivo (€)",
                                              "pct_objetivo": "% previsto"}).round(2)
    dormidos_informe = dormidos.rename(columns={"cliente": "Cliente", "comercial": "Comercial",
                                                "compra_media_mes": "Compra media/mes (€)",
                                                "ultima_compra": "Última compra"}).round({"Compra media/mes (€)": 0})
    st.download_button("📥 Descargar informe en Excel",
                       data=crear_informe(resumen, tabla_informe, dormidos_informe, analisis_informe),
                       file_name=f"informe_ventas_{corte:%Y_%m_%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary", width="stretch")
    st.caption("Incluye el resumen, los comerciales, los clientes dormidos y el último análisis del asistente.")
