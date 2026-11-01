# Especificación · Previsión de Ventas para Mortales 📊

Una buena especificación es la que otro asistente de IA podría construir sin haceros preguntas.

## 1. Problema y usuario

- **Quién tiene el problema:** el responsable comercial de una PYME distribuidora (ejemplo: una distribuidora de gafas que vende a ópticas, con 4 comerciales por zonas) y sus comerciales.
- **Cómo lo resuelve hoy:** exporta las ventas del ERP a Excel, las suma a mano y estima el cierre del mes "a ojo" o con una regla de tres.
- **Qué le molesta de cómo lo hace hoy:** le lleva tiempo cada semana, cada uno calcula distinto, y cuando ve que no llega ya es demasiado tarde para reaccionar. Además, los números no le dicen qué hacer.
- **Qué parte resuelve la IA:** convierte los números en un diagnóstico en lenguaje llano, propone tres acciones concretas (qué comercial, a qué cliente llamar), responde preguntas en un chat y redacta el email o WhatsApp para reactivar a cada cliente dormido.
- **Qué queda fuera de la IA:** los cálculos. La previsión, los objetivos, los clientes dormidos y el simulador los calcula Python con pandas, para que ningún número sea inventado. Esa parte se podría hacer en una hoja de cálculo; lo que no se podría hacer sin IA es la interpretación, la conversación y la redacción de mensajes personalizados.

## 2. Qué hace el producto

1. **Prevé el cierre del mes y lo hace visual.** A partir de un CSV o Excel calcula lo vendido, la previsión de cierre (con rango), el % sobre el objetivo y lo necesario por día laborable. Lo muestra con tarjetas, un termómetro, un gráfico acumulado, globos 🎈 y una **carrera animada de comerciales** 🏁. Además, permite descargar el **informe del lunes en Excel**.
2. **Señala dónde actuar y deja simular.** Incluye un semáforo por comercial, la lista de **clientes dormidos** y un **simulador "¿Y si…?"** (recuperar clientes dormidos, cambiar el ritmo de ventas, añadir un pedido extra) que recalcula el termómetro en directo.
3. **Asistente IA.** Ofrece "✨ Analiza mi mes" con tres **personalidades** (🎩 director serio, 💪 coach, ⚽ locutor de fútbol), botones de **preguntas sugeridas**, un chat con memoria y un **redactor de emails o WhatsApp** para reactivar a cada cliente dormido.

## 3. Entradas y salidas

| El usuario da… | La app devuelve… | Ejemplo |
|---|---|---|
| Un CSV (`,` o `;`) o Excel con columnas `fecha` e `importe` (y, de forma opcional, `comercial` y `cliente`). Se reconocen nombres parecidos (`Fecha factura`, `Importe neto`, `Vendedor`…) | Indicadores, termómetro, gráfico, tabla por comercial y clientes dormidos | `data/ventas_ejemplo.csv` → "Previsión 51.515 € (+3 % vs objetivo)" |
| La fecha de corte, el objetivo del mes (se sugiere el mismo mes del año anterior +10 %) y un filtro por comercial | Los mismos indicadores recalculados | Objetivo 50.000 € → necesario 2.398 €/día |
| Un clic en "✨ Analiza mi mes" | Un diagnóstico de una frase, 3 acciones con nombres reales de los datos y una frase de ánimo con humor | "Llama hoy a Visión Central (Madrid), que compra 1.803 €/mes y este mes no ha pedido" |
| Una pregunta en el chat o un clic en una pregunta sugerida | Una respuesta basada solo en el resumen del mes, con la personalidad elegida | "¿Quién va peor?" → "Javier Martín, al 49 % de su objetivo…" |
| Un cliente dormido, el canal (Email o WhatsApp) y "✍️ Escríbeme el mensaje" | Un mensaje personalizado listo para copiar | Email a Visión Central (Madrid) firmado por Laura Gómez |
| Los deslizadores del simulador "¿Y si…?" | La previsión simulada y su termómetro, con globos si se alcanza el objetivo | Pedido extra de 12.000 € → 63.515 € (+27 %) |
| Un clic en "📥 Descargar informe en Excel" | Un Excel con 4 hojas: resumen, comerciales, clientes dormidos y análisis | `informe_ventas_2026_10_15.xlsx` |

**Método de previsión** (lo calcula Python, no la IA):

- **Ritmo actual** = vendido ÷ días laborables transcurridos × días laborables del mes.
- **Patrón histórico** = vendido ÷ fracción del mes que, de mediana, se había vendido a estas alturas en los 6 meses completos anteriores.
- **Previsión** = media de las dos; el rango va de la menor a la mayor. Si no hay meses anteriores, solo se usa el ritmo actual. Si el mes ya ha terminado, la previsión es lo vendido.

## 4. La pieza de IA

- **Opción elegida:** la API de un LLM, Gemini (`gemini-3.8-flash`, y `gemini-3.5-flash-lite` como reserva si se agota la cuota), con el SDK `google-genai`.
- **Por qué:**
  - El problema no necesita un modelo entrenado (no hay nada que clasificar) ni un RAG (no hay documentos que consultar), sino redactar y razonar sobre unos pocos números.
  - El LLM entiende preguntas libres y escribe en un español natural.
  - Tiene capa gratuita.
  - Solo recibe un resumen en JSON de unos 2 KB, no el fichero completo: gasta menos cuota y no se envían todos los datos.
- **Instrucciones para el modelo (system prompt):** "Eres el asistente de ventas de una PYME. Hablas con un responsable comercial sin perfil técnico. Usa SOLO las cifras del JSON de DATOS DEL MES; si algo no está en los datos, dilo claramente y no lo inventes. No recalcules la previsión: ya viene calculada por la app. Responde en español, con frases cortas y claras, en menos de 180 palabras. Formatea los importes en euros con punto de miles (12.345 €). Si te preguntan algo que no tiene que ver con las ventas, di amablemente que solo puedes ayudar con las ventas del mes."
- **Personalidades** (se añaden al system prompt): director serio y directo; coach motivador y positivo; locutor de fútbol que retransmite el mes como un partido, "pero las cifras deben ser exactas".
- **Prompt del botón "Analiza mi mes"** (reutilizable): "Analiza mi mes. Escribe: 1) Un diagnóstico de una frase (¿llegamos o no al objetivo y por cuánto?). 2) Tres acciones concretas para esta semana que nombren comerciales o clientes reales de los datos. 3) Una frase final de ánimo con un toque de humor."
- **Prompt del redactor de mensajes** (reutilizable): "Escribe un {email | mensaje de WhatsApp} para reactivar a un cliente que suele comprar cada mes y este mes todavía no ha hecho pedido. Cliente, comercial que lo firma, compra media y última compra. En español, cercano y profesional, sin sonar desesperado; ofrece ayuda y termina con una pregunta fácil de contestar. Máximo 120 palabras (email) o 50 palabras (WhatsApp). Devuelve SOLO el texto."

## 5. Flujo del usuario

1. El usuario entra y ve la app con los **datos de ejemplo** ya cargados, así que entiende qué hace sin subir nada.
2. Sube su CSV o Excel y ajusta la fecha de corte, el objetivo y el comercial en la barra lateral.
3. Ve al instante si llega o no (tarjetas de colores, mensaje verde, amarillo o rojo, y globos), el termómetro y el gráfico.
4. Recorre las secciones: 👥 Por comercial, 🏁 Carrera, 🎚️ ¿Y si…?, 😴 Clientes dormidos (donde pide a la IA un email para reactivar a un cliente) y 🔍 ¿Cómo se calcula?
5. Elige la personalidad del asistente, pulsa "✨ Analiza mi mes" o una pregunta sugerida, y sigue preguntando en el chat. Si cambia los datos o el objetivo, la conversación empieza de cero.
6. Descarga el informe en Excel desde la barra lateral para enviarlo al equipo.

## 6. Restricciones

- Coste cero: capa gratuita de la API de Gemini y Streamlit Community Cloud.
- La clave de la API va en secretos (`st.secrets["GEMINI_API_KEY"]`), nunca en el código.
- Sin datos personales reales: los datos de ejemplo son ficticios.
- Lenguaje sencillo, para alguien sin conocimientos técnicos. Importes en formato español.
- La app tiene que funcionar **sin IA**: si no hay clave o falla la API, muestra un análisis automático basado en reglas y plantillas estándar para los mensajes.
- Un solo fichero `app.py`, legible para una principiante en Python.

## 7. Criterios de aceptación

La app está bien si:

| Entrada | Resultado esperado |
|---|---|
| Datos de ejemplo, corte 15/10/2026, objetivo 50.000 € | Previsión ≈ 51.515 €, mensaje verde "Vais camino del objetivo", globos, Javier Martín en rojo |
| CSV con `;`, coma decimal (`1.234,56`) y cabeceras `Fecha factura`/`Importe neto` | Se lee bien y los importes son correctos |
| Fichero con un importe `n/d` o una fecha imposible | Descarta esas filas y avisa de cuántas |
| Fichero sin columna de importe (`data/ejemplo_error_sin_importe.csv`) | Mensaje: "No encuentro la(s) columna(s) importe…", con las columnas que sí hay; la app no se rompe |
| Fichero vacío | "El fichero está vacío." |
| Objetivo = 0 | "Pon un objetivo mayor que 0 €" |
| Solo un mes de datos | Previsión solo con el ritmo actual, explicado en "¿Cómo se calcula?" |
| Sin columna de cliente | Funciona; avisa de que no puede buscar clientes dormidos |
| Pregunta fuera de tema ("¿Qué tiempo hace?") | La IA dice amablemente que solo ayuda con las ventas |
| "✍️ Escríbeme el mensaje" sin IA | Avisa ("Modo sin IA: te dejo una plantilla estándar") y muestra una plantilla firmada por el comercial |
| Carrera con un solo comercial o un fichero sin columna de comercial | "La carrera necesita al menos dos comerciales…" |
| Simulador con un pedido extra de 12.000 € | Previsión simulada de 63.515 € (+27 %) y el termómetro se actualiza |
| Pulsar un botón dentro de una sección | La app se queda en la misma sección (no vuelve a la primera) |
| Se acaba la cuota (429) | Prueba el modelo de reserva; si también falla: "⏳ Se ha agotado la cuota gratuita…", más el análisis automático |
| Sin clave o sin conexión | Mensaje claro, más el análisis automático; el resto de la app funciona igual |

## 8. Fuera de alcance (por ahora)

- Conexión directa con el ERP (hoy se sube un fichero exportado).
- Festivos nacionales y locales en el cálculo de días laborables.
- Objetivos distintos por comercial subidos desde un fichero.
- Envío automático del informe por email cada lunes (hoy se descarga a mano).
- Previsión por producto o familia.

## 9. Despliegue

- **Ruta:** A (Streamlit Community Cloud), desde un repositorio público de GitHub.
- **Trabajo en equipo:** no.
