# Checklist: música y playlists para el Echo Mini

Márcalo en orden. Lo que comprueba `python echomini_tool.py scan EchoMini` lleva **[scan]**.

## 1. Antes de empezar
- [ ] Hay copia de seguridad de la música original.
- [ ] Está decidido si va a la **memoria interna** (8 GB, unas 250 canciones FLAC 24 bit) o a la **microSD**.
- [ ] La carpeta `EchoMini/` es copia de la raíz del aparato: `Music/` y `Playlists/` dentro.

## 2. Nombres y carpetas
- [ ] **[scan]** Ningún nombre lleva `< > : " \ / | ? *`.
- [ ] **[scan]** Ninguna carpeta ni archivo termina en punto o espacio. Ojo con `nano.`: usa `nano`.
- [ ] **[scan]** Ningún nombre pasa de 63 caracteres.
- [ ] **[scan]** Como mucho 5 niveles: `/Music/Artista/Álbum/Canción.flac` son 4.
- [ ] **[scan]** Toda la música está dentro de `/Music/`.
- [ ] Cada `.lrc` se llama igual que su canción. **[scan]** avisa de las letras sueltas.

## 3. Etiquetas (de ellas sale la Biblioteca)
- [ ] **[scan]** Todas tienen título, artista y álbum.
- [ ] **[scan]** Todas tienen número de pista.
- [ ] **[scan]** Cada álbum tiene un solo "artista del álbum"; si no, se parte en la Biblioteca.
- [ ] **[scan]** Duplicados revisados.

## 4. Portadas
- [ ] **[scan]** Todas tienen portada incrustada.
- [ ] Probado en el aparato con 2–3 canciones si las portadas grandes (1400–2000 px) se ven bien y sin lentitud.
- [ ] Si no: `covers --apply` las reduce a 500×500 en JPEG normal y sustituyes por las copias.
- [ ] **[scan]** No quedan portadas progresivas ni en PNG (solo si hiciste el paso anterior).

## 5. Letras
- [ ] `lrc --apply` ejecutado: sin marcas `v1:` ni tiempos por palabra, y con `.lrc` creados desde la letra incrustada.
- [ ] **[scan]** Las letras están en UTF-8.
- [ ] **[scan]** Las letras sin tiempos `[mm:ss.xx]` están revisadas: se busca la versión sincronizada (lrclib.net) o se aceptan sin sincronizar.

## 6. Playlists
- [ ] Una lista de canciones por playlist: CSV de Exportify (con ISRC) o TXT `Título - Artista`.
- [ ] `playlist` ejecutado para cada una.
- [ ] Revisado el `*_revision.txt` de cada una: no encontradas (descargar o corregir) y dudosas (confirmar).
- [ ] **[scan]** Ninguna ruta de playlist apunta a un archivo que no existe.
- [ ] **[scan]** Ninguna playlist pasa de 500 canciones (si pasa, se parte en varias).
- [ ] Playlists y canciones en la **misma** memoria.

## 7. Revisión final
- [ ] `scan` da **0 errores**.
- [ ] Los avisos que quedan están entendidos y aceptados.

## 8. En el Echo Mini
- [ ] Contenido de `EchoMini/` copiado a la raíz de la memoria elegida; fuera la microSD si va a la interna.
- [ ] Biblioteca actualizada desde su menú.
- [ ] Canciones, portadas y artistas bien en la Biblioteca.
- [ ] La letra se ve y se sincroniza (ajuste de letras activado).
- [ ] Una `.m3u8` abierta desde **Navegación por carpetas** suena, y aparece en **Biblioteca → M3U Playlist**.
- [ ] Si dice **"Format Not Supported!"**: rutas mal (repite `scan`) o prueba `playlist ... --crlf`.
