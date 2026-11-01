# 📊 Previsión de Ventas para Mortales

**Enlace a la app:** https://prevision-ventas-salespulse.streamlit.app/

**Autora: Abril Alonso Gutiérrez** ✏️ 

## Pitch

1. A mitad de mes, el responsable comercial de una PYME no sabe si va a llegar al objetivo: lo calcula a ojo en un Excel y, cuando ve el problema, ya es tarde.
2. Previsión de Ventas para Mortales lee el Excel de ventas y en segundos dice cómo se cerrará el mes, cuánto hay que vender cada día, qué comercial va por detrás y qué clientes habituales no han comprado todavía.
3. La IA convierte esos números en un plan: diagnostica el mes en lenguaje llano (incluso como un locutor de fútbol), propone acciones con nombres reales y redacta el email para reactivar a cada cliente dormido. Todo esto no saldría de una hoja de cálculo.
4. Al probarla descubrí que las fechas en formato `2026-10-15` se leían al revés y se perdían 807 de 1.364 ventas sin que nadie se diera cuenta; ahora la app detecta el formato y avisa de cada fila que descarta.
5. Con los datos de ejemplo, el día 15 la app ya señala 14 clientes dormidos que suman unos 14.700 € al mes, casi un 30 % del objetivo: el siguiente paso es conectarla al ERP y enviar este aviso automáticamente cada lunes.

## El problema

El responsable comercial de una PYME distribuidora (por ejemplo, de gafas que se venden a ópticas) exporta cada semana las ventas del ERP a Excel y estima el cierre del mes con una regla de tres. Le lleva tiempo, cada persona calcula distinto y los números no le dicen qué hacer. Cuando descubre que no va a llegar, ya no hay margen para reaccionar. Detectarlo a mitad de mes, con nombres concretos, es la diferencia entre llegar al objetivo o no.

## Qué hace la app

1. Abres la app y ves los **datos de ejemplo** ya cargados, o subes tu CSV o Excel (basta con una columna de fecha y otra de importe).
2. En la barra lateral eliges la **fecha de corte**, el **objetivo** y, si quieres, un comercial.
3. Ves al momento si llegas o no: tarjetas de colores, termómetro, gráfico de ventas acumuladas y globos 🎈 si vas bien.
4. Navegas por las secciones:
   - 👥 **Por comercial:** semáforo de cada uno frente a su objetivo.
   - 🏁 **Carrera:** animación de los comerciales compitiendo hacia la meta.
   - 🎚️ **¿Y si…?:** simulador para recuperar clientes, subir el ritmo o añadir un pedido grande.
   - 😴 **Clientes dormidos:** lista de clientes y redactor de emails o WhatsApp con IA para reactivarlos.
   - 🔍 **¿Cómo se calcula?:** la explicación del método.
5. En el **asistente** eliges su personalidad (🎩 serio, 💪 coach, ⚽ locutor de fútbol), pulsas **✨ Analiza mi mes** o una pregunta sugerida, y sigues conversando en el chat.
6. Descargas el **informe del lunes en Excel** desde la barra lateral.

## La pieza de IA

- **Qué usa:** la API de Gemini con el modelo `gemini-3.8-flash` y `gemini-3.5-flash-lite` como reserva, mediante el SDK `google-genai`.
- **Por qué esa opción:** el problema no necesita entrenar un modelo ni consultar documentos (RAG), sino interpretar unos pocos números, conversar y redactar en español, que es lo que mejor hace un LLM. La IA no calcula nada: recibe un resumen en JSON que ya ha calculado Python, así que no puede inventarse las cifras, y además gasta muy poca cuota.
- **Qué pasa si falla:** si se agota la cuota (429), la app lo intenta con el modelo de reserva. Si tampoco funciona, o no hay clave o no hay conexión, muestra un mensaje claro ("⏳ Se ha agotado la cuota gratuita…", "🔑 La clave no es válida…", "📡 No he podido conectar…") junto con un análisis automático basado en reglas, o una plantilla estándar en el caso de los emails. El resto de la app sigue funcionando igual.
- **Dónde está la clave:** en Settings → Secrets de Streamlit Community Cloud. Nunca en el código ni en el repositorio.

## Cómo la he construido

- **Herramientas:** Claude (asistente de IA con ejecución de código) para la idea, la especificación, el código y las pruebas, a partir de la plantilla de Streamlit del curso.
- **Fichero de contexto del agente:** [AGENTS.md](AGENTS.md), y [CLAUDE.md](CLAUDE.md) y [GEMINI.md](GEMINI.md), que remiten a él.
- **Prompts clave:**
  1. "tenemos que hacer una app que solucione un problema del día a día, que sea interesante y divertida" → "sería más de una empresa" → "más"
  2. "haremos la 15, esto es lo que me piden: [enunciado del reto]"
  3. "[plantillas del reto y app.py de la plantilla de Streamlit]": adaptar el proyecto a las plantillas del curso.
  4. "si quiero hacerla más espectacular aún?" → "hagamos las 6": simulador, carrera, emails con IA, personalidades, informe en Excel y diseño.
  5. [Captura del error `FileNotFoundError`]: arreglar que la app no encontraba los datos de ejemplo al desplegarla.
- **Qué delegué al agente y qué revisé a mano:**
  - Delegué: la estructura de `app.py`, el método de previsión, la lectura de ficheros con formatos distintos, los mensajes de error, los datos de ejemplo y las mejoras visuales.
  - Revisé a mano: ✏️ completa con lo que hayas hecho tú. Por ejemplo: que la previsión de los datos de ejemplo cuadra con una regla de tres en Excel; que en el repositorio no aparece ninguna clave; que los textos se entienden sin conocimientos técnicos; la configuración de Secrets en Streamlit, donde corregí el nombre `GEMINI_API_KEY_2` por `GEMINI_API_KEY`.

## Prueba y mejora

| Quién la probó | Qué probó | Qué pasó | Qué cambié |
|---|---|---|---|
| Yo como usuaria (criterios de aceptación) | Los datos de ejemplo con fechas `2026-10-15` | Se descartaban 807 de 1.364 filas: las fechas se leían como día-mes al revés y la previsión salía mal | Ahora la app detecta si las fechas vienen en formato ISO o español antes de leerlas |
| Yo como usuaria | "Analiza mi mes" sin clave de API | El mensaje decía "no puedo responder preguntas libres", aunque no había hecho ninguna pregunta | Cambié el texto a "Modo sin IA: no hay clave configurada…" |
| Yo como usuaria | Pulsar "✍️ Escríbeme el mensaje" dentro de la pestaña "Clientes dormidos" | Al pulsar el botón, la app volvía a la primera pestaña y el mensaje quedaba escondido | Cambié las pestañas (`st.tabs`) por un selector (`st.segmented_control`) que recuerda la sección elegida |
| Yo como usuaria, en la app desplegada | Abrir la app con los datos de ejemplo | Error `FileNotFoundError`: la carpeta `data` no se había subido a GitHub | Subí la carpeta y cambié el mensaje para que diga qué falta y cómo arreglarlo |
| Yo como usuaria, en la app desplegada | El asistente IA | Salía "Modo sin IA" porque el secreto se llamaba `GEMINI_API_KEY_2` y estaba partido en dos líneas | Corregí el secreto a una sola línea, `GEMINI_API_KEY = "…"` |

## Ejecutar en local (opcional)

```bash
pip install -r requirements.txt
# Poned la clave en .streamlit/secrets.toml (copiad secrets.toml.example) y ejecutad
streamlit run app.py
```

## Capturas

1. **La app funcionando:** ✏️ captura
2. **Caso límite:** al subir `ejemplo_error_sin_importe.csv` sale el mensaje "No encuentro la columna importe…". ✏️ captura
3. **Trabajo con la IA:** ✏️ captura de este chat
4. **La prueba:** ✏️ captura
