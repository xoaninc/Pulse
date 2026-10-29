# Música para el Echo Mini: instrucciones para Claude

Habla con el usuario en español. Este kit sirve para preparar su música y sus playlists para un
**Snowsky / FiiO Echo Mini de 8 GB** y dejarlas listas para copiar al aparato.

## Situación actual

- El Echo Mini ya tiene el **firmware oficial V4.0.0** (el que añade las playlists M3U) con un tema
  "Cyberdeck" en 5 colores. Está instalado y funciona, así que no hay que tocar el firmware.
- En Ajustes, el estilo de interfaz va: 1 blanco, 2 negro, 3 rosa, 4 azul, 5 naranja.
- El usuario descarga su música en **FLAC 24 bit / 44,1 kHz**. Los archivos traen buenas etiquetas
  (título, artista, álbum, artista del álbum, pista, disco, ISRC), la portada incrustada y la letra
  dentro del archivo. Además tienen al lado un `.lrc` con el mismo nombre (`Título - Artista.flac` y
  `Título - Artista.lrc`).
- Lo que se vio en sus primeras descargas:
  - **Portadas enormes** (1400–2000 px).
  - **Letras con marcas `v1:`** delante de cada línea, que se verían en pantalla.
  - **Letras sin tiempos** (`[mm:ss.xx]`), que no se sincronizan.
  - Un artista llamado **`nano.`**: una carpeta que termina en punto no sirve en la memoria del Echo
    Mini (FAT), porque Windows quita el punto y la ruta deja de coincidir.

## Cómo se organiza

Trabaja en una carpeta del PC que sea **copia exacta de la raíz del Echo Mini** (la "raíz").
Después el usuario copia su contenido tal cual a la memoria interna o a la microSD:

```
EchoMini/                                        <- raíz
  Music/<Artista del álbum>/<Álbum>/<Título - Artista>.flac
  Music/<Artista del álbum>/<Álbum>/<Título - Artista>.lrc
  Playlists/<Nombre>.m3u8
```

- **Playlists y canciones en la misma memoria**: o todo en la interna o todo en la microSD.
- La interna tiene 8 GB, unas 250 canciones FLAC de 24 bit. Si no cabe, usa la microSD.
- No renombres la música del usuario sin preguntarle. Si se renombra una canción, su `.lrc` también
  y con el mismo nombre. Después hay que regenerar las playlists.

## Reglas del Echo Mini

Las marcadas con (*) salen del análisis del firmware V4.0.0 y no se han probado en el aparato.

**Formatos de audio:** FLAC, MP3, WAV, APE, M4A, OGG, WMA y DSD.

**Nombres (sistema de archivos FAT/exFAT):**
- No se pueden usar `< > : " \ / | ? *`.
- Ninguna carpeta ni archivo puede **terminar en punto o espacio**.
- Cada nombre de carpeta o archivo, como mucho **63 caracteres** (*).

**Biblioteca:**
- Se ordena con las **etiquetas**, no con los nombres de archivo: álbum por disco, luego número de
  pista, luego nombre de archivo.
- Todas las canciones de un álbum deben tener el **mismo "artista del álbum"**; si no, el álbum se
  parte en varios.
- Después de copiar música nueva hay que **actualizar la biblioteca** en el aparato.

**Portadas:**
- Van **incrustadas** en cada archivo.
- Se recomienda JPEG normal (no progresivo) de unos **500×500**. Es un margen prudente para una
  pantalla de 320×170, pero el límite real no está comprobado: pide al usuario que pruebe 2–3
  canciones antes de convertir todo.

**Letras:**
- Un `.lrc` al lado de la canción, con exactamente el mismo nombre, en **UTF-8**.
- Solo se sincronizan las líneas con tiempo: `[00:04.44]Texto`.
- Quita las marcas `v1:` y los tiempos por palabra `<00:01.23>`.
- Hay un ajuste de letras en el aparato para activarlas o desactivarlas.

**Playlists `.m3u8`** (*):
- Codificación UTF-8 (también acepta UTF-16). Una ruta por línea; las líneas con `#` se ignoran.
- Rutas absolutas desde la raíz con `/`: `/Music/Amaia/Álbum/Canción.flac`. Si llevan letra de unidad
  (`E:`), se ignora. Las relativas parten de la carpeta de la playlist.
- Como mucho 5 niveles de carpeta y archivo, 259 caracteres por línea y **500 canciones por lista**.
- Si ninguna ruta coincide, el aparato dice **"Format Not Supported!"**.
- Uso: el `.m3u8` se abre desde **Navegación por carpetas**. Después la lista aparece en
  **Biblioteca → M3U Playlist**, pero solo la que esté cargada; para cambiar, se abre otro `.m3u8`.
- Si una lista correcta no carga, prueba a generarla con `--crlf` (saltos de línea de Windows).

## Herramienta: `echomini_tool.py`

Necesita Python 3.8 o superior y solo usa la biblioteca estándar. El comando `covers` además
necesita Pillow (`pip install pillow`). Si `mutagen` está instalado, también lee las etiquetas de
formatos que no son FLAC.

```
python echomini_tool.py scan RAIZ
    Revisa todo y escribe informe_echomini.md. Termina con código 1 si hay errores.
python echomini_tool.py lrc RAIZ [--apply]
    Limpia los .lrc y crea el .lrc desde la letra incrustada si falta. Sin --apply solo muestra lo
    que haría; con --apply guarda antes una copia en _backup_lrc/.
python echomini_tool.py playlist RAIZ --input LISTA.csv|.txt --name "Nombre" [--crlf]
    Crea RAIZ/Playlists/Nombre.m3u8 y un Nombre_revision.txt con las canciones no encontradas y
    las dudosas.
python echomini_tool.py covers RAIZ --out SALIDA [--size 500] [--apply]
    Reduce las portadas de los FLAC. Escribe copias en SALIDA y no toca los originales ni el audio.
```

**Entrada de `playlist`:**
- **CSV de Exportify** (exportify.app, para playlists de Spotify; trae ISRC y empareja exacto) o de
  TuneMyMusic.
- O un **TXT** con una línea por canción, `Título - Artista` (también vale `Artista - Título`).

**Cómo empareja:** primero por ISRC, luego por título y artista, luego solo título si es único, y por
último por parecido (≥ 85 %). Lo que no sea exacto se apunta en el archivo de revisión.

## Cómo trabajar

1. **Pregunta al usuario:**
   - dónde está su música en el PC;
   - si va a la memoria interna o a la microSD;
   - de dónde salen las playlists (Spotify con Exportify, capturas, listas escritas);
   - si quiere renombrar.
2. **Prepara la raíz** `EchoMini/` con la estructura de arriba (copiando, no moviendo).
3. **Revisa:** `scan`. Arregla todos los **ERROR** consultando al usuario (nombres con punto final,
   nombres demasiado largos, caracteres no válidos). Comenta los **AVISO**.
4. **Letras:** `lrc` en seco, enseña el resumen y luego `lrc --apply`. Para las letras sin tiempos,
   propón buscar la versión sincronizada (lrclib.net) o dejarlas como están.
5. **Portadas:** si en la prueba del aparato no salen o va lento, ejecuta `covers --apply` y
   sustituye los archivos por las copias de SALIDA.
6. **Playlists:** una ejecución de `playlist` por lista. Revisa con el usuario las no encontradas y
   las dudosas.
7. **Revisión final:** repite `scan` hasta llegar a **0 errores**. Repasa `CHECKLIST.md`.
8. **Al aparato:** el usuario copia el contenido de la raíz, actualiza la biblioteca y prueba una
   playlist.

**Nunca:**
- borres música del usuario;
- sobrescribas originales sin copia;
- toques el firmware ni los archivos `.IMG`.
