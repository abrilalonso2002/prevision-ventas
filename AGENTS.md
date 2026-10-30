# AGENTS.md · Previsión de Ventas para Mortales

> Este fichero lo leen los agentes de programación antes de tocar el código. `CLAUDE.md` y `GEMINI.md` solo dicen: "Sigue las instrucciones de AGENTS.md".

## Qué es este proyecto

App que dice a un responsable comercial de una PYME, sin perfil técnico, si va a llegar al objetivo de ventas del mes, qué comerciales y clientes necesitan atención y qué hacer esta semana, con un asistente de IA que lo explica en lenguaje llano.

## Cómo está hecho

- Python 3.12.
- Interfaz: Streamlit (ruta A).
- IA: API de Gemini con el SDK `google-genai`. El modelo está en la constante `MODELO` de `app.py` (con `MODELO_RESERVA` para cuando se agota la cuota).
- Cálculos: pandas y numpy. Gráficos: plotly.
- Archivos: `app.py` (toda la app), `requirements.txt` (dependencias), `README.md`, `especificacion.md` y `data/` (CSV de ejemplo, todos ficticios).
- La especificación completa está en [especificacion.md](especificacion.md). Si algo de este fichero contradice la especificación, manda la especificación.

## Reglas

- La clave de la API va SIEMPRE en secretos (`st.secrets["GEMINI_API_KEY"]`). Nunca en el código, en el README ni en el chat.
- Cada llamada a la API va dentro de `try/except` y muestra un mensaje claro para el usuario (función `mensaje_de_error`). Nunca se enseña una traza de Python al usuario.
- **La IA nunca calcula números.** Los cálculos se hacen en pandas (`prever_cierre`, `clientes_dormidos`); a la IA solo se le envía el resumen JSON para que lo explique.
- La app tiene que funcionar sin clave de API, usando `analisis_sin_ia`.
- Textos de la interfaz en español, sencillos y con un punto de humor. Los importes siempre con `eur()` (`12.345 €`).
- Código sencillo: funciones cortas con docstring en español, sin clases. La autora está aprendiendo Python y tiene que entenderlo todo.
- Cambios pequeños: uno por petición. Al terminar, explica qué has cambiado y por qué.
- Si añades una librería, añádela también a `requirements.txt` y dilo.
- No uses datos personales reales. Para probar, inventa ejemplos.

## Cómo comprobar que funciona

- `streamlit run app.py` en local (con `.streamlit/secrets.toml`), o haz push y revisa la app en Streamlit Cloud.
- Casos de prueba (entrada → lo que esperamos):
  1. Datos de ejemplo, corte 15/10/2026, objetivo 50.000 € → previsión ≈ 51.515 €, mensaje verde y globos.
  2. `data/ejemplo_formato_espanol.csv` (`;` y coma decimal) → 3 filas válidas y un aviso de 1 importe descartado.
  3. `data/ejemplo_error_sin_importe.csv` → mensaje "No encuentro la(s) columna(s) importe…" y la app no se rompe.
  4. Sin `secrets.toml` → aviso "Modo sin IA" y análisis automático al pulsar "Analiza mi mes".
  5. Pregunta fuera de tema en el chat ("¿Qué tiempo hace en Madrid?") → la app dice amablemente que solo puede ayudar con las ventas.

## Qué no hacer

- No borres ni reescribas el README sin preguntar.
- No cambies el modelo ni la arquitectura sin preguntar.
- No hagas que la IA calcule la previsión.
- No hagas push ni despliegues sin que yo lo haya revisado.
