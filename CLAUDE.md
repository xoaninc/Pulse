# Cazador de arte involuntario · notas para Claude Code

Herramienta hecha a medida para el **Ejercicio 2.3 · Fotografía** del Grado en Paisajismo (URJC). Habla con la alumna en **castellano**; textos de la interfaz y comentarios del código, también en castellano.

## La entrega (lo que manda)

- **Fechas:** entrega virtual el **jueves 29 de octubre a las 23:59**; en papel, el viernes 30. Prioriza siempre lo que mejore la entrega de esta noche.
- **4 láminas A3 apaisadas**, cada una con 6 fotos **cuadradas en color** (2 filas × 3 columnas). En total, 24 fotos de «arte involuntario» de Gilles Clément que intenten cubrir las 8 categorías: Vuelos, Acumulaciones, Islas, Construcciones, Erosiones, Instalaciones, Huellas y Apariciones. La categoría va escrita bajo cada foto.
- **2 láminas A3 apaisadas** con **12 o más fotos cuadradas en blanco y negro** de un paseo por un paisaje natural, al estilo de Hamish Fulton. Bajo cada foto va una frase sobre un suceso singular, y se marcan el origen y el final.
- Se pueden usar fotos ya hechas: la app busca en la fototeca de Fotos de la alumna.

## Su Mac y su fototeca (informe del 29 oct)

- macOS 27, Apple Silicon. Fototeca de **59.826 fotos**, casi todas **solo en iCloud** (59.755: «Optimizar almacenamiento»). Todas están analizadas con el modelo `rapido` (MobileCLIP2-S2).
- Solo **11.713 fotos tienen GPS**, y 56.138 tienen etiquetas de Fotos, **en inglés** («Document», «People»…).
- **Más de la mitad no son fotos de cámara.** Etiquetas más frecuentes: Document 30.782, People 19.869, Art 13.057, Cartoon 6.925, Anime 3.175, Comics 2.539, Manga 2.214, Video Game 1.350, Clip Art 1.263, Drawing 1.557, Handwriting 1.535, Printed Page 1.460…
- **Selección actual:** 12 fotos de arte (Acumulaciones 2, Construcciones 1, Erosiones 3, Instalaciones 1, Huellas 3, Apariciones 1, Islas 1). Vuelos no tiene ninguna, y el paseo no está empezado.
- **Paseos detectados: 49.** Los mejores candidatos:
  - 21 jun 2026, Sierra Norte de Sevilla: 87 fotos (49 de naturaleza), 29,5 km, 6,9 h.
  - 21 feb 2026, San Pablo (Jimena de la Frontera): 159 fotos, 33,5 km.
  - 30 jul 2026, Alfoz de Lloredo: 22 fotos, 12,8 km.
- `./arte informe` deja en `salida/informe/` una hoja de contacto por categoría (con las 30 primeras candidatas), la selección, los paseos y `resumen.txt`. **Míralas con Read**: con la fototeca real, ese es el banco de pruebas.

## Lo que ha dicho la alumna y diagnóstico

**Sus palabras:** «Vuelos funciona muy mal; Huellas, Erosiones y Acumulaciones, bien. Salen fotos artificiales o cosas no relacionadas con el tema.»

**Lo que se ve en las hojas de contacto:**

1. **No se filtra lo que no es una foto de cámara.**
   - Capturas, memes, dibujos, anime e imágenes descargadas o de WhatsApp solo se detectan por `p.screenshot` (campo `captura`) o por `global.etiquetas_excluir` en `categorias.json`.
   - Esa lista no tiene `cartoon`, `anime`, `comics`, `manga`, `clip art`, `video game` ni `drawing`.
   - Además solo **penaliza un poco** (`puntuar.penal_meta`), no excluye.
2. **Vuelos.** CLIP encuentra «bolsa de plástico», pero no «enganchada por el viento». Salen manos sujetando bolsas, bolsas de comida para llevar, comida en papel de aluminio, juguetes, fotos oscuras o movidas y fotos a través de un cristal. Las primeras (cinta en un árbol junto al río, bolsa en un arbusto del camino, globo en un árbol) sí valen.
3. **Islas.** Salen paisajes llanos y vacíos o carreteras al atardecer, muchas veces a través de la ventanilla del coche o del tren: está el vacío, pero falta el objeto pequeño.
4. **Construcciones.** Salen edificios corrientes, andenes, vallas y andamios, en lugar de lo apilado o lo apañado.
5. **Calidad.** Hay fotos muy oscuras, movidas o desenfocadas, y nada usa las puntuaciones de calidad de Fotos salvo `score.overall` (campo `estetica`).

## Qué hacer, por orden

1. **Excluir de verdad lo que no es foto de cámara.**
   - En `fuentes.foto_de_photoinfo`, guardar la cámara: `p.exif_info.camera_make` / `camera_model`, comprobado en osxphotos 0.77 (`osxphotos/exifinfo.py`).
   - Marcar como no-foto también la `uti` o el nombre original de imágenes de WhatsApp (`IMG-AAAAMMDD-WA…`), las descargas y las capturas.
   - En `puntuar.py`, sacar esas fotos de las candidatas de todas las categorías y de los paseos, salvo que no quede casi nada.
   - Añadir a `etiquetas_excluir`: cartoon, anime, comics, manga, clip art, video game, drawing, toy, sticker.
   - «Art» trae 13.057 fotos y puede incluir grafitis útiles para Huellas, así que **no** la excluyas del todo.
   - Para que el índice coja los campos nuevos basta con `./arte analizar`: `indice.registrar` hace INSERT OR REPLACE de los datos. Los vectores se conservan porque la `firma` (ruta + fecha de modificación) no cambia, así que es solo la lectura con osxphotos, unos minutos.
   - Compara `./arte informe` antes y después.
2. **Calidad.** Guardar algunas puntuaciones de `p.score` (ScoreInfo): `failure`, `sharply_focused_subject`, `low_light`, `pleasant_lighting`. Penalizar el fallo alto o el poco enfoque y, si hace falta, la oscuridad medida en la miniatura, solo para el top-N.
3. **Vuelos.**
   - Confusores nuevos: «a hand holding a plastic bag», «a takeaway food bag», «food wrapped in aluminium foil», «a plastic bag on a floor indoors», «a toy», «a blurry dark photo», «a photo taken through a car window».
   - Prompts que insistan en: al aire libre, enganchada o colgando, contra ramas o cielo.
4. **Islas.**
   - Confusores: «an empty flat landscape seen through a car window», «a road at sunset», «a field seen from a train window».
   - Prompts siempre con el objeto pequeño.
5. **Construcciones.** Confusores: andén de tren, fachada moderna, valla metálica, andamio en un edificio corriente.
6. **IA opcional (Groq).** Ya está hecha en `ia.py` y en la galería, con los botones ✨ «Revisar con IA» por categoría y «frases del paseo».
   - Hace falta `ia.env` con `GROQ_API_KEY=gsk_…` en la raíz (está en .gitignore; no la imprimas nunca).
   - Antes de usarlo, **comprueba en la consola de Groq que el modelo de visión de `ia.MODELO_DEFECTO` sigue existiendo**.
   - Útil sobre todo en Vuelos. Las notas se guardan en `datos/ia_notas.json` y suben o bajan candidatas con `ia.ajuste()`.
   - Si se quiere en bloque, añadir `./arte ia --categoria vuelos --n 60`.
7. **Paseo.** Ayudarla a elegir el recorrido (el de Sierra Norte parece el mejor), proponer 12–16 fotos y escribir frases propias. La IA puede proponer borradores, pero las frases deben ser suyas y verdaderas.

## Cómo está hecho (mapa rápido)

| Fichero | Qué hace |
|---|---|
| `arte_involuntario/cli.py` | órdenes: analizar, galeria, laminas, estado, limpiar, todo, informe |
| `fuentes.py` | lee Fotos con osxphotos (previsualizaciones locales aunque el original esté en iCloud, GPS, altitud del blob ZLOCATIONDATA, etiquetas, puntuación); también carpetas |
| `indice.py` | SQLite `datos/fototeca.sqlite`: tablas fotos, vectores (float16 por modelo, con firma), meta |
| `modelo.py` | open_clip MobileCLIP2 (`rapido` = S2, `preciso` = S4), MPS/CPU |
| `textos.py` | embeddings de las frases de `categorias.json`, en caché `datos/textos/` (clave = hash del modelo y del config) |
| `puntuar.py` | puntuación por categoría: z robusto + especificidad + contraste con confusores + arte + etiquetas + estética − exclusiones; pesos en `PESOS` |
| `paseos.py` | detecta caminatas (huecos de tiempo y GPS), km con limpieza de picos, sugiere k fotos, sucesos (frases) relativos al paseo |
| `servidor.py` + `web/` | galería local en 127.0.0.1:8765 (http.server + JS sin frameworks); la selección se guarda en `datos/seleccion.json` con `_rev` (409 si hay conflicto) |
| `generar.py` + `laminas.py` + `imagenes.py` | láminas: PDF con reportlab (fuentes incrustadas, Futura en Mac), JPG, P3→sRGB, B/N en modo L |
| `descargas.py` + `exportar_photokit.py` | al generar, baja de iCloud los originales de las fotos elegidas mediante un proceso hijo con PhotoKit (siempre como foto fija); si falla, usa la previsualización |
| `icloud.py` | `analizar --traer-icloud`: miniaturas reducidas de las fotos sin imagen local |
| `ia.py` | Groq opcional (API compatible con OpenAI) |
| `informe.py` | `./arte informe` |
| `categorias.json` | por categoría: prompts, confusores, etiquetas de Apple, definición y consejos; además `global` (arte, excluir) y `paseo` (naturaleza, urbano, camino, sucesos) |

## Reglas para trabajar aquí

- **No borres `datos/`** ni ejecutes `./arte limpiar --todo`: el índice de 59.826 fotos tarda en rehacerse. `datos/seleccion.json` es el trabajo de la alumna.
- La galería guarda cada cambio al momento. Para que coja cambios del código Python hay que reiniciarla (Ctrl+C y `./arte galeria`); la selección no se pierde. No edites `seleccion.json` con la galería abierta.
- Tras cada ajuste de puntuación: `./arte informe` y mirar las hojas. Los cambios en `categorias.json` regeneran solos la caché de textos.
- **Pruebas:** `.venv/bin/python -m pytest -q` (65 pruebas, sin modelo ni fototeca). Si faltan pytest o pyflakes:
  ```bash
  PATH="$PWD/.uv:$PATH" uv pip install --python .venv/bin/python pytest pyflakes
  ```
  Antes de cada commit: `.venv/bin/python -m pyflakes arte_involuntario tests`.
- **Git:** rama `arte-involuntario` de github.com/xoaninc/pulse. Es una rama huérfana: el `main` de ese repo es otro proyecto, **nunca la mezcles**. Para subir: `git push origin HEAD:arte-involuntario`.
- No probado aún en un Mac real (vigílalo la primera vez):
  - la descarga de originales con PhotoKit, y que el proceso hijo tenga el permiso de Fotos de la Terminal;
  - el registro de Futura;
  - `--traer-icloud`.
  - Si una descarga falla, la lámina sale con la previsualización (~1.024 px) y un aviso de baja resolución.
