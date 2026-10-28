# Cazador de arte involuntario 📷

Herramienta para el **Ejercicio 2.3 · Fotografía** (Bloque 2 *Observar/Documentar*, Grado en Paisajismo, URJC).
Busca en tu fototeca de Fotos (aunque esté en iCloud) las fotos que encajan en las **8 categorías de arte involuntario de Gilles Clément** y las **caminatas** que sirven para el **paseo al estilo Hamish Fulton**. Después te deja elegir y recortar en una galería y **monta las 6 láminas A3** en PDF y JPG.

- 4 láminas A3 apaisadas, 6 fotos **cuadradas en color** (2 filas × 3 columnas), con la categoría rotulada: *Vuelos, Acumulaciones, Islas, Construcciones, Erosiones, Instalaciones, Huellas, Apariciones*.
- 2 láminas A3 apaisadas con **≥ 12 fotos cuadradas en blanco y negro** de un recorrido, con **ORIGEN** y **FINAL**, una palabra-título y una frase bajo cada foto, al estilo Fulton.

Todo funciona **en tu Mac, sin internet** (salvo la primera descarga del modelo). No se sube ninguna foto a ningún sitio, salvo que actives tú el filtro opcional con IA.

---

## 1 · Antes de empezar (2 minutos)

**Dale permiso a la Terminal para leer la fototeca.** macOS protege la fototeca:

1. *Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco*.
2. Activa **Terminal** (o pulsa **+** y añádela desde *Aplicaciones → Utilidades*).
3. Cierra la Terminal por completo (⌘Q) y vuelve a abrirla.

**Espacio:** la app ocupa unos **2 GB** (Python y librerías ~1,3 GB + modelo ~0,4 GB) y no descarga tus fotos de iCloud para analizarlas. El instalador no sigue si quedan menos de 5 GB libres.

## 2 · Instalar

El código vive en la rama `arte-involuntario` del repo `xoaninc/pulse` (rama independiente, sin nada de Pulse):

```bash
cd ~/Documents
git clone -b arte-involuntario --single-branch https://github.com/xoaninc/pulse.git arte-involuntario
cd arte-involuntario
./instalar.sh
```

Sin git: en GitHub cambia a la rama **arte-involuntario** → *Code → Download ZIP*, descomprímelo, abre la Terminal en esa carpeta (clic derecho sobre la carpeta → *Nuevo terminal en la carpeta*) y ejecuta `./instalar.sh`. Si macOS no deja ejecutarlo: `chmod +x instalar.sh arte Empezar.command`.

Todo se instala **dentro de la carpeta** (`.venv/`, `.python/`). Para desinstalarlo basta con borrar la carpeta.

> Atajo: haz doble clic en **`Empezar.command`**. Instala si hace falta, analiza y abre la galería. La primera vez macOS puede avisar de que es de un desarrollador no identificado: clic derecho → *Abrir*.

## 3 · Analizar la fototeca

```bash
./arte analizar
```

- Lee la fototeca de **Fotos** con [osxphotos](https://github.com/RhetTbull/osxphotos), sin tocarla: solo lee.
- **iCloud y «Optimizar almacenamiento»:** analiza las **previsualizaciones** que Fotos ya guarda en el Mac, así que **no descarga nada**. Las fotos sin previsualización local se saltan y te dice cuántas son.
- La primera vez descarga el modelo de visión (~400 MB). Luego va todo sin internet.
- Es **incremental**: si lo cortas con Ctrl+C no pierdes lo hecho, y la próxima vez solo procesa las fotos nuevas.

Opciones útiles:

| Orden | Para qué |
|---|---|
| `./arte analizar --desde 2023-01-01` | solo fotos desde esa fecha (más rápido) |
| `./arte analizar --album "Viajes"` | solo un álbum |
| `./arte analizar --carpeta ~/Desktop/fotos` | una carpeta en vez de la app Fotos |
| `./arte analizar --modelo preciso` | modelo más fino (descarga 1,7 GB, ~4× más lento) |

## 4 · Elegir y montar en la galería

```bash
./arte galeria
```

Se abre el navegador (`http://127.0.0.1:8765`, que solo funciona en tu Mac). Tiene tres pestañas:

**1 · Arte involuntario**
- A la izquierda están las 8 categorías. Cada una muestra sus candidatas de más a menos probable.
- *Buscar solo:* son frases concretas de cada categoría (p. ej. «sneakers hanging from power lines»). Pulsa una para ver solo ese tipo de foto.
- El buscador acepta lo que quieras, mejor en inglés: `rusty gate`, `plastic bag in a tree`, `hay bales in a field`…
- **≈ Ver fotos parecidas** en el visor sirve para tirar del hilo cuando encuentras una buena.
- Abajo, la bandeja muestra las 4 láminas. Haz clic en una foto elegida para **mover el recorte cuadrado** y escribir el **pie**. El pie lleva por defecto el lugar y la fecha, como en el libro: «Arrozal en Suzhou, lago Tai (China)».
- **★ Lo más «Clément»** reúne las mejores de todas las categorías.

**2 · Paseo**
- Lista las **caminatas detectadas**, agrupadas por fecha y GPS y ordenadas según cuánto paisaje natural tienen. Si la tuya no sale, usa *Elegir fechas a mano*.
- Propone 12 fotos repartidas a lo largo del recorrido. Haz clic en cualquier foto para añadirla o quitarla. La primera es el **ORIGEN** y la última el **FINAL**.
- Cada foto lleva un borrador de frase con **hora · km · altitud** (si hay GPS) y un «suceso» detectado («Un perro cruza el camino»). **Cámbialo por lo que pasó de verdad.** Es lo que pide Fulton.
- Eliges la **palabra-título** (como LIZARDS o CLOUDS), la línea de la caminata, si las frases van en mayúsculas, si se dibuja el recorrido o el perfil de altitud (como los murales de Fulton) y el diseño: rejilla, o fotos que crecen a lo largo del recorrido como en *Within Sight* de Helen Sear.

**3 · Láminas**
- Escribe tu nombre, elige el orden y el contraste del B/N y pulsa **Generar PDF y JPG**.
- Si alguna foto elegida está solo en iCloud, se descarga **solo esa** (la app Fotos puede abrirse sola). Si no se puede, usa la previsualización y te avisa de que quizá salga blanda impresa.

Resultado, en la carpeta `salida/`:

```
entrega_completa.pdf          ← las 6 láminas A3 (para la entrega virtual)
01_arte_involuntario.pdf      ← 4 láminas
02_paseo_fotografico.pdf      ← 2 láminas
lamina_1_arte.jpg … lamina_6_paseo.jpg   (200 ppp)
fotos_arte/  fotos_paseo/     ← cada foto ya recortada a 300 ppp, para imprimir suelta
```

## 5 · Liberar espacio al acabar

```bash
./arte estado          # qué ocupa cada cosa
./arte limpiar         # borra originales descargados y cachés (conserva selección y láminas)
./arte limpiar --todo  # además borra el modelo y el índice
```

O borra la carpeta entera.

---

## Filtro opcional con IA (Groq u otra API compatible con OpenAI)

La clasificación local acierta bien con lo concreto (bolsas, zapatillas en cables, troncos apilados, óxido) y peor con lo abstracto (*Islas*, *Apariciones*). Si quieres un segundo filtro barato:

1. Saca una clave en <https://console.groq.com/keys>.
2. Crea un archivo `ia.env` en esta carpeta con:
   ```
   GROQ_API_KEY=gsk_...
   # opcional:
   # ARTE_IA_MODELO=meta-llama/llama-4-scout-17b-16e-instruct
   ```
3. Abre la galería. Aparecerán los botones **✨ Revisar con IA**, que puntúa de 0 a 10 las 30 primeras candidatas de la categoría abierta y explica por qué, y **✨ Proponer frases con IA** en el paseo.

Solo se envían **miniaturas de 512 px** de las fotos que pidas revisar. Una pasada por las 8 categorías cuesta céntimos.

---

## Cómo funciona

1. **Previsualizaciones locales.** `fuentes.py` lee la base de datos de Fotos con osxphotos. Para cada foto usa la mayor previsualización local; si no hay ninguna, el original.
2. **Visión-lenguaje (CLIP).** `modelo.py` usa [open_clip](https://github.com/mlfoundations/open_clip) con *MobileCLIP2* de Apple, en la GPU del Mac (MPS). Convierte cada foto y cada frase en un vector comparable.
3. **Categorías de Clément** (`categorias.json`). Cada categoría tiene unas 40 frases concretas en inglés, sacadas del texto de Clément, de los ejemplos del libro y de ejemplos ampliados, más unos «confusores» (cosas que se le parecen pero no lo son).
4. **Puntuación** (`puntuar.py`). Combina:
   - el parecido con las frases, normalizado sobre tu fototeca;
   - cuánto destaca esa categoría sobre las demás;
   - el contraste con los confusores;
   - las etiquetas que Fotos ya asigna («Plastic Bag», «Rust»…);
   - penalizaciones para selfies, capturas, comida o documentos.
   Los pesos se ajustaron con las 39 fotos de ejemplo de las diapositivas mezcladas con 1.000 fotos cotidianas.
5. **Caminatas** (`paseos.py`). Agrupa las fotos por huecos de tiempo y saltos de GPS, mide los km y el tanto por ciento de paisaje natural, y elige 12 fotos repartidas en el tiempo.
6. **Láminas** (`laminas.py`). La maqueta se define en milímetros y se dibuja en PDF vectorial (reportlab) y en JPG. En el Mac usa **Futura**, la tipografía de Fulton.

## Problemas frecuentes

- **«macOS no deja leer la fototeca»** → falta el *Acceso total al disco* para la Terminal (paso 1). Después hay que reiniciar la Terminal.
- **«N fotos no tienen ninguna imagen en este Mac»** → son fotos solo en iCloud sin previsualización. Abre la app Fotos y deja que termine de sincronizar, o analiza solo lo que tengas.
- **Una foto elegida sale blanda** → no se pudo bajar el original de iCloud. Abre la foto en la app Fotos (se descarga), cierra la galería y vuelve a generar.
- **Falta una categoría** → mira *Qué buscar* en esa categoría: hay ideas para hacer la foto mañana mismo (una bolsa en una valla, palés apilados, una mancha de óxido, unas gaviotas alineadas…).
- **La caminata no aparece** → *Elegir fechas a mano* en la pestaña Paseo.

## Pruebas

```bash
uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -q
```
