# Cazador de arte involuntario 📷

Herramienta para el **Ejercicio 2.3 · Fotografía** (Bloque 2 *Observar/Documentar*, Grado en Paisajismo, URJC).
Busca en tu fototeca de Fotos (aunque esté en iCloud) las fotos que encajan en las **8 categorías de arte involuntario de Gilles Clément** y las **caminatas** que sirven para el **paseo al estilo Hamish Fulton**. Después te deja elegir y recortar en una galería y **monta las 6 láminas A3** en PDF y JPG:

- **4 láminas A3 apaisadas** con 6 fotos **cuadradas en color** en 2 filas × 3 columnas y la categoría rotulada bajo cada foto (*Vuelos, Acumulaciones, Islas, Construcciones, Erosiones, Instalaciones, Huellas, Apariciones*).
- **2 láminas A3 apaisadas** con **12 o más fotos cuadradas en blanco y negro** de un recorrido: **ORIGEN** y **FINAL** marcados, una palabra-título, la línea de la caminata y una frase bajo cada foto, como en las obras de Fulton.

Todo funciona **en tu Mac**. Solo necesita internet para instalarse y para descargar el modelo la primera vez. Ninguna foto sale de tu ordenador, salvo que actives tú el filtro opcional con IA.

---

## 1 · Antes de empezar (2 minutos)

1. **Usa la app Terminal de macOS** (Aplicaciones → Utilidades → Terminal), no iTerm ni la terminal de VS Code: los permisos de Fotos se conceden a la app de terminal.
2. **Dale permiso a la Terminal para leer la fototeca**: *Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco* → activa **Terminal** (si no sale, pulsa **+** y añádela). Después **cierra la Terminal con ⌘Q** y vuelve a abrirla.
3. **Cierra la app Fotos** mientras analizas (si está abierta, su base de datos está bloqueada y hay que copiarla aparte).

**Espacio:** la app ocupa unos **2 GB**: Python y librerías ~1,3 GB más el modelo, ~0,4 GB. Para analizar no descarga tus fotos de iCloud, y siempre deja un margen libre para macOS.

## 2 · Instalar (sin git ni herramientas de desarrollo)

Copia y pega en la Terminal estas líneas: descargan la app en tu carpeta de inicio y la instalan. Tarda 5-10 minutos.

```bash
cd ~
curl -L https://github.com/xoaninc/pulse/archive/refs/heads/arte-involuntario.tar.gz | tar xz
mv Pulse-arte-involuntario arte-involuntario
cd arte-involuntario
./instalar.sh
```

> ¿Por qué en la carpeta de inicio y no en Documentos o Escritorio? Esas dos carpetas suelen sincronizarse con iCloud Drive: subirías 2 GB a tu iCloud y macOS podría quitar archivos de la app cuando falte espacio. El instalador avisa si la pones ahí.

**Otra opción, con el navegador:** en GitHub, rama `arte-involuntario` → *Code → Download ZIP*. Descomprímelo y mueve la carpeta a tu carpeta de inicio. En la Terminal escribe `cd ` (con un espacio), arrastra la carpeta a la ventana, pulsa Intro y ejecuta `./instalar.sh`.

Todo se instala **dentro de la carpeta** (`.venv/`, `.python/`, `.uv/`). Para desinstalar, basta con borrarla.

> **Atajo con doble clic:** `Empezar.command` instala si hace falta, analiza y abre la galería. Si macOS dice que «no se puede verificar» el archivo: pulsa *Aceptar*, ve a *Ajustes del Sistema → Privacidad y seguridad*, baja hasta *Seguridad* y pulsa **Abrir igualmente** (en macOS 15 y 26 ya no sirve clic derecho → Abrir). Si lo has instalado con `./instalar.sh`, el aviso ya no aparece.

### Actualizar a la última versión

Si ya la tienes instalada y sale un arreglo, cierra la galería (Ctrl+C en su Terminal) y pega esto. Cambia los archivos de la app por los nuevos y **conserva** lo instalado (`.venv/`), lo analizado y tu selección (`datos/`), las láminas (`salida/`) y tu `ia.env`:

```bash
cd ~/arte-involuntario && rm -rf .nueva && mkdir .nueva \
  && curl -fL https://github.com/xoaninc/pulse/archive/refs/heads/arte-involuntario.tar.gz | tar xz -C .nueva \
  && cp -R .nueva/Pulse-arte-involuntario/. . \
  && rm -rf .nueva && ./instalar.sh
```

Si tu carpeta está en otro sitio o tiene otro nombre, cambia `~/arte-involuntario` por su ruta. No vuelvas a pegar el bloque de instalación: como la carpeta ya existe, `mv` metería la versión nueva dentro de la vieja y seguirías usando la antigua.

## 3 · Analizar la fototeca

```bash
./arte analizar
```

- Lee la fototeca de **Fotos** con [osxphotos](https://github.com/RhetTbull/osxphotos). Solo lee, no cambia nada.
- **iCloud y «Optimizar almacenamiento»:** analiza las **previsualizaciones** que Fotos guarda en el Mac aunque el original esté en la nube (~1.024 px, con su GPS), así que **no descarga nada**.
- Si alguna foto no tiene ninguna imagen local, te dice cuántas son. Para incluirlas: `./arte analizar --traer-icloud`. Pide a iCloud una versión reducida (~100 KB por foto, nunca el original) y necesita el permiso *Ajustes → Privacidad y seguridad → Fotos → Terminal → Acceso completo*.
- La primera vez descarga el modelo de visión (~400 MB).
- Es **incremental**: puedes cortarlo con **Ctrl+C** y lo analizado queda guardado; la próxima vez solo procesa lo nuevo.
- **Tiempos orientativos:** en un Mac con chip M, unos minutos por cada 10.000 fotos. En un Mac Intel va a unas 3-5 fotos/s: 10.000 fotos son unos 45 minutos. Si vas justo de tiempo, usa `--desde` (abajo) o pulsa Ctrl+C cuando lleve un rato: la galería funciona con lo ya analizado (empieza por las fotos más recientes).

| Orden | Para qué |
|---|---|
| `./arte analizar --desde 2023-01-01` | solo fotos desde esa fecha (más rápido) |
| `./arte analizar --desde 2025-05-11 --hasta 2025-05-11` | solo un día (incluido) |
| `./arte analizar --album "Viajes"` | solo un álbum |
| `./arte analizar --carpeta ~/Desktop/fotos` | una carpeta en vez de la app Fotos |
| `./arte analizar --modelo preciso` | modelo más fino (descarga 1,8 GB, ~3× más lento); la galería lo usa en cuanto termina de analizarlas todas (si lo cortas, sigue con el anterior) |

## 4 · Elegir y montar en la galería

```bash
./arte galeria
```

Se abre el navegador en `http://127.0.0.1:8765` (solo funciona en tu Mac). Deja la ventana de Terminal abierta mientras la usas. Tu selección se guarda sola.

**1 · Arte involuntario**
- A la izquierda están las 8 categorías. Cada una muestra sus candidatas de más a menos probable y te avisa si tiene pocas.
- *Buscar solo:* son frases concretas de cada categoría (p. ej. «sneakers hanging from power lines»). Pulsa una para ver solo ese tipo de foto; lo que añadas desde ahí va a esa categoría.
- **Buscador libre, en castellano:** «bolsa de plástico en un árbol», «verja oxidada», «zapatillas colgadas de cables», «gaviotas en fila sobre un muro»…
- **≈ Ver fotos parecidas** en el visor sirve para tirar del hilo cuando encuentras una buena. Con ← → pasas de foto.
- Abajo, la bandeja muestra las 4 láminas. Pulsa una foto elegida para **mover el recorte cuadrado** y escribir el **pie**. Por defecto lleva el lugar y la fecha, como en el libro: «Arrozal en Suzhou, lago Tai (China)».
- **★ Lo más «Clément»** reúne las mejores de todas las categorías.

**2 · Paseo**
- Lista las **caminatas detectadas**, agrupadas por fecha y GPS y ordenadas según cuánto paisaje natural tienen. Si la tuya no sale, usa *Elegir fechas a mano*.
- Propone 12, 14 o 16 fotos repartidas por el recorrido. Pulsa cualquier foto para añadirla o quitarla. La primera es el **ORIGEN** y la última el **FINAL**.
- Cada foto trae un borrador de frase con el «suceso» que se ve («Un perro cruza el camino», «La niebla llena el valle»). **Cámbialo por lo que pasó de verdad**, que es lo que pide Fulton. La hora, los km y la altitud se ponen solos debajo de cada foto.
- Eliges la **palabra-título** (como LIZARDS o CLOUDS), la línea de la caminata, frases en mayúsculas o no, si se dibuja el **perfil o recorrido** (como los murales de Fulton) y el diseño: rejilla, o fotos que **crecen** a lo largo del recorrido (*Within Sight* de Helen Sear).
- Si miras otra caminata o cambias el número de fotos, **no pierdes lo escrito**: cada caminata guarda su borrador.

**3 · Láminas**
- Escribe tu nombre, elige el orden y el contraste del B/N y pulsa **Generar PDF y JPG**.
- Las fotos elegidas que solo están en iCloud se descargan **una a una, solo esas**, en su versión editada. La primera vez macOS pide permiso para que la Terminal acceda a Fotos: elige *Acceso completo*. Si iCloud no responde, se usa la previsualización y te avisa. La casilla **No descargar** lo salta del todo.
- En **«Revisa:»** aparecen los avisos: categorías que faltan, fotos que se verán blandas impresas (indica la lámina y la posición), frases vacías o demasiado largas, etc.

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
./arte limpiar         # cachés y originales que ya no usas (conserva modelo, índice, selección y láminas)
./arte limpiar --todo  # además borra el modelo, el índice y los originales descargados
```

O borra la carpeta entera. Los originales que se descargan de iCloud también se quedan dentro de tu fototeca de Fotos (36 fotos ≈ 100-300 MB) hasta que iCloud vuelva a optimizar el espacio.

---

## Filtro opcional con IA (Groq u otra API compatible con OpenAI)

La clasificación local acierta bien con lo concreto (bolsas, zapatillas en cables, troncos apilados, óxido) y peor con lo abstracto (*Islas*, *Apariciones*). Si quieres un segundo filtro barato:

1. Saca una clave gratuita en <https://console.groq.com/keys>.
2. En la Terminal, dentro de la carpeta del proyecto (no uses TextEdit):
   ```bash
   echo 'GROQ_API_KEY=gsk_TU_CLAVE' > ia.env
   ```
3. Abre la galería. Aparecerán **✨ Revisar con IA**, que puntúa de 0 a 10 las 12 primeras candidatas de la categoría abierta y explica por qué, y **✨ Proponer frases con IA** en el paseo. La IA nunca sustituye una frase que hayas escrito tú: te la ofrece debajo.

Usa el modelo de visión de Groq `qwen/qwen3.8-27b`. Solo se envían **miniaturas de 768 px** de las fotos que pidas revisar. En el plan gratuito va lento (unas 3 fotos por petición y poco margen por minuto) pero cuesta 0 €.

---

## Cómo funciona

1. **Previsualizaciones locales** (`fuentes.py`). Lee la base de datos de Fotos con osxphotos y usa la previsualización local de ~1.024 px de cada foto, más la altitud, el lugar, las etiquetas y la puntuación estética que Fotos ya calculó.
2. **Visión-lenguaje** (`modelo.py`). Usa [open_clip](https://github.com/mlfoundations/open_clip) con *MobileCLIP2* de Apple, en la GPU del Mac (MPS), y convierte cada foto y cada frase en un vector comparable.
3. **Categorías de Clément** (`categorias.json`). Unas 45 frases concretas en inglés por categoría, sacadas del texto de Clément, de los ejemplos de las diapositivas y de ejemplos ampliados, más unos «confusores» (cosas que se le parecen pero no lo son) y reglas para los casos dudosos. Ejemplo: pacas de heno esparcidas → Acumulaciones; apiladas → Construcciones; formando una figura → Instalaciones; una sola en un rastrojo → Islas.
4. **Puntuación** (`puntuar.py`). Combina:
   - el parecido con las frases, normalizado sobre tu fototeca;
   - cuánto destaca esa categoría sobre las demás;
   - el contraste con los confusores;
   - las etiquetas de Fotos;
   - penalizaciones para selfies, capturas, comida o documentos.
   Ajustado con las 39 fotos de las diapositivas mezcladas con 1.000 fotos cotidianas.
5. **Caminatas** (`paseos.py`). Agrupa las fotos por huecos de tiempo y saltos de GPS (ignorando posiciones erróneas), mide los km y el porcentaje de paisaje natural, y elige fotos repartidas en el tiempo.
6. **Láminas** (`laminas.py`). La maqueta se define en milímetros y se dibuja en PDF vectorial (reportlab, con fuentes incrustadas) y en JPG. Las fotos del iPhone pasan de Display P3 a sRGB para que no salgan apagadas. El blanco y negro protege las sombras para imprimir en reprografía. En el Mac usa **Futura**, la tipografía de Fulton.

## Problemas frecuentes

- **«macOS no deja leer la fototeca»** → falta el *Acceso total al disco* para la Terminal (paso 1). Después cierra la Terminal con ⌘Q y vuelve a abrirla.
- **«No encuentro tu fototeca»** → abre la app Fotos una vez; si tu fototeca está en otro sitio: `./arte analizar --biblioteca "/ruta/a/Fotos.photoslibrary"`.
- **«No hay espacio suficiente…»** → el mensaje dice cuánto falta. Cierra la app Fotos si estaba abierta y vacía la Papelera.
- **«La instalación no está completa»** → vuelve a ejecutar `./instalar.sh`.
- **No se descargan las fotos de iCloud** → *Ajustes → Privacidad y seguridad → Fotos → Terminal → Acceso completo* (con «acceso limitado» no ve las fotos). Si no hay prisa, marca *No descargar* y usa las previsualizaciones.
- **Falta una categoría** → mira *Qué buscar* en esa categoría: hay ideas para hacer la foto mañana mismo (una bolsa enganchada en una valla, palés apilados, una mancha de óxido, unas gaviotas alineadas…).
- **La caminata no aparece** → *Elegir fechas a mano* en la pestaña Paseo.
- **Otro error** → `ARTE_DEPURAR=1 ./arte …` muestra los detalles técnicos.

## Pruebas

```bash
.uv/uv pip install --python .venv/bin/python pytest 2>/dev/null || uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -q
```
