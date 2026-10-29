#!/usr/bin/env python3
"""Prepara una biblioteca de musica para el Snowsky / FiiO Echo Mini (firmware V4.0.0).

Trabaja sobre una carpeta del PC que es copia exacta de la raiz del Echo Mini (la "raiz"):

    EchoMini/                 <- RAIZ (lo que copias a la memoria interna o a la microSD)
      Music/Artista/Album/Titulo - Artista.flac
      Music/Artista/Album/Titulo - Artista.lrc
      Playlists/Mi lista.m3u8

Comandos (todos aceptan --config echomini_config.json):
  scan     RAIZ                      revisa nombres, rutas, etiquetas, portadas, letras y playlists
                                     y escribe informe_echomini.md en la carpeta actual
  lrc      RAIZ [--apply]            limpia las letras .lrc (marcas "v1:", tiempos por palabra) y crea
                                     el .lrc desde la letra incrustada si falta; sin --apply solo
                                     muestra lo que haria (antes de cambiar guarda copia en _backup_lrc/)
  playlist RAIZ --input LISTA --name NOMBRE [--crlf]
                                     crea Playlists/NOMBRE.m3u8 a partir de un CSV (Exportify,
                                     TuneMyMusic...) o un TXT con lineas "Titulo - Artista"
  covers   RAIZ --out SALIDA [--size 500] [--apply]
                                     reduce las portadas incrustadas de los FLAC a JPEG normal de
                                     SIZE px; escribe copias en SALIDA (no toca los originales).
                                     Necesita Pillow:  pip install pillow

Solo usa la biblioteca estandar de Python 3.8+ (Pillow solo para "covers"; mutagen, si esta
instalado, para leer etiquetas de formatos que no son FLAC).
"""
import argparse, csv, difflib, hashlib, io, json, os, re, shutil, struct, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

DEFAULTS = {
    "music_dir": "Music",
    "playlist_dir": "Playlists",
    "audio_ext": [".flac", ".mp3", ".m4a", ".wav", ".ape", ".ogg", ".wma", ".aac", ".dsf", ".dff"],
    "max_component_chars": 63,
    "max_components": 5,
    "max_line_chars": 259,
    "max_tracks": 500,
    "cover_max_px": 500,
    "capacity_gb": 8,
}
BAD_CHARS = set('<>:"\\|?*')
TIME_TAG = re.compile(r'^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]')
VOICE = re.compile(r'^((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)\s*v\d+:\s*')
WORD_TIME = re.compile(r'<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>')


def load_config(path):
    cfg = dict(DEFAULTS)
    candidates = [Path(path)] if path else [Path(__file__).with_name('echomini_config.json')]
    for c in candidates:
        if c.is_file():
            cfg.update(json.load(open(c, encoding='utf-8')))
    return cfg


# ---------------------------------------------------------------- lectura de FLAC (sin dependencias)

def jpeg_info(data):
    """(ancho, alto, progresivo, submuestreo) de un JPEG, o None si no es JPEG."""
    if data[:2] != b'\xff\xd8':
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack('>H', data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            h, w = struct.unpack('>HH', data[i + 5:i + 9])
            n = data[i + 9]
            factors = [data[i + 11 + 3 * k] for k in range(n)]
            sub = '4:4:4' if len(set(factors)) == 1 else ('4:2:0' if factors[0] == 0x22 else '4:2:2')
            return w, h, marker == 0xC2, sub
        i += 2 + seg
    return None


def read_flac(path):
    """Devuelve dict con streaminfo, etiquetas (MAYUSCULAS -> lista) e imagenes, o None."""
    with open(path, 'rb') as f:
        if f.read(4) != b'fLaC':
            return None
        info = {'tags': defaultdict(list), 'pictures': []}
        while True:
            head = f.read(4)
            if len(head) < 4:
                break
            last, btype, size = head[0] & 0x80, head[0] & 0x7F, int.from_bytes(head[1:4], 'big')
            body = f.read(size)
            if btype == 0:
                x = int.from_bytes(body[10:18], 'big')
                info['rate'] = x >> 44
                info['channels'] = ((x >> 41) & 7) + 1
                info['bits'] = ((x >> 36) & 31) + 1
                samples = x & ((1 << 36) - 1)
                info['seconds'] = samples / info['rate'] if info['rate'] else 0
            elif btype == 4:
                vlen = struct.unpack('<I', body[:4])[0]
                p = 4 + vlen
                count = struct.unpack('<I', body[p:p + 4])[0]
                p += 4
                for _ in range(count):
                    ln = struct.unpack('<I', body[p:p + 4])[0]
                    entry = body[p + 4:p + 4 + ln].decode('utf-8', 'replace')
                    p += 4 + ln
                    if '=' in entry:
                        k, v = entry.split('=', 1)
                        info['tags'][k.upper()].append(v)
            elif btype == 6:
                p = 0
                ptype, = struct.unpack('>I', body[p:p + 4]); p += 4
                ml, = struct.unpack('>I', body[p:p + 4]); p += 4
                mime = body[p:p + ml].decode('ascii', 'replace'); p += ml
                dl, = struct.unpack('>I', body[p:p + 4]); p += 4 + dl
                w, h, depth, colors, n = struct.unpack('>IIIII', body[p:p + 20]); p += 20
                img = body[p:p + n]
                info['pictures'].append({'type': ptype, 'mime': mime, 'w': w, 'h': h, 'bytes': n,
                                         'jpeg': jpeg_info(img)})
            if last:
                break
        return info


def read_other(path):
    """Etiquetas de MP3/M4A/... con mutagen si esta instalado; None si no se puede."""
    try:
        import mutagen
    except ImportError:
        return None
    try:
        m = mutagen.File(path, easy=True)
    except Exception:
        return None
    if m is None:
        return None
    tags = defaultdict(list)
    for k, v in (m.tags or {}).items():
        tags[k.upper()] = list(v) if isinstance(v, list) else [str(v)]
    has_cover = False
    try:
        raw = mutagen.File(path)
        has_cover = any(k.startswith('APIC') for k in (raw.tags or {})) or 'covr' in (raw.tags or {}) \
            or bool(getattr(raw, 'pictures', None))
    except Exception:
        pass
    return {'tags': tags, 'pictures': [{'type': 3, 'mime': '?', 'w': 0, 'h': 0, 'bytes': 0, 'jpeg': None}] if has_cover else [],
            'seconds': getattr(getattr(m, 'info', None), 'length', 0)}


def read_audio(path):
    return read_flac(path) if path.suffix.lower() == '.flac' else read_other(path)


def tag(info, *keys):
    for k in keys:
        if info and info['tags'].get(k):
            return info['tags'][k][0].strip()
    return ''


# ---------------------------------------------------------------- utilidades

def norm(s):
    """Texto comparable: sin acentos, minusculas, sin parentesis/feat ni signos."""
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\((?:feat|ft|with|con)[^)]*\)|\[(?:feat|ft)[^\]]*\]', ' ', s)
    s = re.sub(r'\s(?:feat|ft)\.?\s.*$', ' ', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


def split_artists(s):
    return [a for a in (norm(x) for x in re.split(r'[;,/&]|\bfeat\.?|\bft\.?|\by\b|\bx\b', s or '')) if a]


def device_path(root, p):
    return '/' + p.relative_to(root).as_posix()


def audio_files(root, cfg):
    exts = {e.lower() for e in cfg['audio_ext']}
    return sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in exts
                  and not any(part.startswith('.') for part in p.relative_to(root).parts))


def path_problems(dev, cfg):
    out = []
    parts = dev.strip('/').split('/')
    for c in parts:
        if len(c) > cfg['max_component_chars']:
            out.append(('ERROR', f'nombre de {len(c)} caracteres (max {cfg["max_component_chars"]}): "{c}"'))
        bad = sorted(set(c) & BAD_CHARS) + [ch for ch in c if ord(ch) < 32]
        if bad:
            out.append(('ERROR', f'caracteres no validos en FAT/exFAT {bad}: "{c}"'))
        if c != c.rstrip(' .'):
            out.append(('ERROR', f'termina en punto o espacio (Windows/FAT lo recorta y la ruta deja de coincidir): "{c}"'))
    if len(parts) > cfg['max_components']:
        out.append(('ERROR', f'{len(parts)} niveles de carpeta+archivo (max {cfg["max_components"]} para playlists)'))
    if len(dev) > cfg['max_line_chars']:
        out.append(('ERROR', f'ruta de {len(dev)} caracteres (max {cfg["max_line_chars"]})'))
    return out


def lrc_report(path):
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
        enc = 'UTF-8'
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
        enc = 'NO UTF-8'
    lines = [l for l in text.splitlines() if l.strip()]
    timed = [l for l in lines if TIME_TAG.match(l)]
    meta = [l for l in lines if re.match(r'^\[[a-z]+:', l)]
    return {'enc': enc, 'lines': len(lines) - len(meta), 'timed': len(timed),
            'voice': sum(1 for l in lines if VOICE.match(l)), 'words': sum(1 for l in lines if WORD_TIME.search(l))}


def clean_lrc_text(text):
    out = []
    for line in text.splitlines():
        line = VOICE.sub(r'\1', line)
        line = WORD_TIME.sub('', line)
        out.append(line.rstrip())
    return '\n'.join(out).strip() + '\n'


# ---------------------------------------------------------------- scan

def cmd_scan(args, cfg):
    root = Path(args.root).resolve()
    files = audio_files(root, cfg)
    issues = []                                    # (nivel, ruta, mensaje)
    add = lambda lvl, where, msg: issues.append((lvl, where, msg))
    albums = defaultdict(set)
    seen = defaultdict(list)
    total = 0
    formats = Counter()
    for p in files:
        dev = device_path(root, p)
        total += p.stat().st_size
        for lvl, msg in path_problems(dev, cfg):
            add(lvl, dev, msg)
        if not dev.lower().startswith('/' + cfg['music_dir'].lower() + '/'):
            add('AVISO', dev, f'fuera de /{cfg["music_dir"]}/')
        info = read_audio(p)
        if info is None:
            add('INFO', dev, 'no se pudieron leer las etiquetas (instala mutagen para formatos que no son FLAC)')
            continue
        if 'bits' in info:
            formats[f'FLAC {info["bits"]} bit / {info["rate"] / 1000:g} kHz'] += 1
        else:
            formats[p.suffix.lower()] += 1
        title, artist, album = tag(info, 'TITLE'), tag(info, 'ARTIST'), tag(info, 'ALBUM')
        albumartist = tag(info, 'ALBUMARTIST', 'ALBUM ARTIST', 'ALBUM_ARTIST')
        for name, val in (('titulo', title), ('artista', artist), ('album', album)):
            if not val:
                add('AVISO', dev, f'sin etiqueta de {name}')
        if not tag(info, 'TRACKNUMBER', 'TRACK'):
            add('AVISO', dev, 'sin numero de pista (el album saldra desordenado)')
        if album:
            albums[(album, os.path.dirname(dev))].add(albumartist or artist)
        seen[(norm(artist), norm(title))].append(dev)
        pics = info['pictures']
        front = next((x for x in pics if x['type'] == 3), pics[0] if pics else None)
        if not front:
            add('AVISO', dev, 'sin portada incrustada')
        elif front['mime'] != '?':
            j = front['jpeg']
            if not j:
                add('AVISO', dev, f'portada en {front["mime"]} (mejor JPEG)')
            else:
                w, h, prog, sub = j
                if max(w, h) > cfg['cover_max_px']:
                    add('AVISO', dev, f'portada de {w}x{h} (recomendado <= {cfg["cover_max_px"]}px; usa "covers")')
                if prog:
                    add('AVISO', dev, 'portada JPEG progresiva (mejor JPEG normal/baseline; usa "covers")')
        if len(pics) > 1:
            add('INFO', dev, f'{len(pics)} imagenes incrustadas (solo hace falta la portada)')
        lrc = p.with_suffix('.lrc')
        if lrc.exists():
            r = lrc_report(lrc)
            if r['enc'] != 'UTF-8':
                add('AVISO', device_path(root, lrc), 'letra no esta en UTF-8 (puede verse con simbolos raros)')
            if r['timed'] == 0:
                add('AVISO', device_path(root, lrc), 'letra sin tiempos [mm:ss.xx]: no se sincroniza (busca la version con tiempos, p. ej. lrclib.net)')
            if r['voice'] or r['words']:
                add('AVISO', device_path(root, lrc), 'letra con marcas "v1:" o tiempos por palabra (usa "lrc --apply")')
        else:
            emb = '\n'.join(info['tags'].get('LYRICS', []) + info['tags'].get('UNSYNCEDLYRICS', []))
            if emb and any(TIME_TAG.match(l) for l in emb.splitlines()):
                add('INFO', dev, 'tiene letra con tiempos incrustada pero falta el .lrc (usa "lrc --apply")')
    for (album, folder), arts in albums.items():
        if len(arts) > 1:
            add('AVISO', folder, f'album "{album}" con varios "artista del album" {sorted(arts)}: se partira en la Biblioteca')
    for key, devs in seen.items():
        if len(devs) > 1 and key != ('', ''):
            add('INFO', devs[0], f'posible duplicado ({len(devs)} archivos): ' + ' | '.join(devs))
    for lrc in sorted(root.rglob('*.lrc')):
        if not any(lrc.with_suffix(e).exists() for e in cfg['audio_ext']) and \
           not any(lrc.with_suffix(e.upper()).exists() for e in cfg['audio_ext']):
            add('AVISO', device_path(root, lrc), 'letra sin cancion con el mismo nombre al lado')
    pls = sorted(list(root.rglob('*.m3u')) + list(root.rglob('*.m3u8')))
    for pl in pls:
        for lvl, msg in check_playlist(root, pl, cfg):
            add(lvl, device_path(root, pl), msg)

    gb = total / 1e9
    order = {'ERROR': 0, 'AVISO': 1, 'INFO': 2}
    issues.sort(key=lambda x: (order[x[0]], x[1]))
    counts = Counter(i[0] for i in issues)
    lines = [f'# Informe Echo Mini', '', f'- Raiz: `{root}`', f'- Canciones: {len(files)} ({gb:.2f} GB; memoria interna {cfg["capacity_gb"]} GB)',
             f'- Formatos: ' + ', '.join(f'{k}: {v}' for k, v in formats.most_common()), f'- Playlists: {len(pls)}',
             f'- Problemas: {counts["ERROR"]} errores, {counts["AVISO"]} avisos, {counts["INFO"]} notas', '']
    if gb > cfg['capacity_gb'] * 0.95:
        lines.insert(3, f'- **No cabe en la memoria interna**: usa la microSD para parte de la musica')
    for lvl in ('ERROR', 'AVISO', 'INFO'):
        group = [i for i in issues if i[0] == lvl]
        if group:
            lines += [f'## {lvl} ({len(group)})', '']
            lines += [f'- `{w}`: {m}' for _, w, m in group]
            lines.append('')
    report = Path(args.report or 'informe_echomini.md')
    report.write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines[:8]))
    print(f'\nInforme completo: {report.resolve()}')
    return 1 if counts['ERROR'] else 0


def check_playlist(root, pl, cfg):
    out = []
    raw = pl.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16')
    else:
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            return [('ERROR', 'no esta en UTF-8 ni UTF-16')]
    entries = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('#')]
    if len(entries) > cfg['max_tracks']:
        out.append(('ERROR', f'{len(entries)} canciones (max {cfg["max_tracks"]})'))
    if not entries:
        out.append(('ERROR', 'vacia: el Echo Mini dira "Format Not Supported!"'))
    lower = {str(p.relative_to(root).as_posix()).lower(): p for p in root.rglob('*') if p.is_file()}
    missing = 0
    for e in entries:
        if len(e) > cfg['max_line_chars']:
            out.append(('ERROR', f'linea de {len(e)} caracteres: {e[:60]}...'))
        path = re.sub(r'^[A-Za-z]:', '', e).replace('\\', '/')
        if path.startswith('/'):
            rel = path.lstrip('/')
        else:
            rel = (pl.parent.relative_to(root) / path).as_posix()
        rel = os.path.normpath(rel).replace('\\', '/')
        hit = lower.get(rel.lower())
        if not hit:
            missing += 1
            if missing <= 20:
                out.append(('ERROR', f'no existe: {e}'))
        elif hit.relative_to(root).as_posix() != rel:
            out.append(('INFO', f'mayusculas distintas (FAT no distingue, suele dar igual): {e}'))
        for c in rel.split('/'):
            if len(c) > cfg['max_component_chars']:
                out.append(('ERROR', f'nombre de mas de {cfg["max_component_chars"]} caracteres en: {e}'))
                break
    if missing > 20:
        out.append(('ERROR', f'... y {missing - 20} rutas mas que no existen'))
    return out


# ---------------------------------------------------------------- lrc

def cmd_lrc(args, cfg):
    root = Path(args.root).resolve()
    backup = Path('_backup_lrc').resolve()
    changed = created = 0
    for lrc in sorted(root.rglob('*.lrc')):
        raw = lrc.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            print(f'[no UTF-8, revisar a mano] {device_path(root, lrc)}')
            continue
        new = clean_lrc_text(text)
        if new.strip() != '\n'.join(l.rstrip() for l in text.splitlines()).strip():
            changed += 1
            print(f'[limpiar] {device_path(root, lrc)}')
            if args.apply:
                dst = backup / lrc.relative_to(root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(lrc, dst)
                lrc.write_text(new, encoding='utf-8')
    for p in audio_files(root, cfg):
        lrc = p.with_suffix('.lrc')
        if lrc.exists():
            continue
        info = read_audio(p)
        if not info:
            continue
        emb = next((v for k in ('LYRICS', 'UNSYNCEDLYRICS') for v in info['tags'].get(k, [])
                    if any(TIME_TAG.match(l) for l in v.splitlines())), None)
        if emb:
            created += 1
            print(f'[crear desde la letra incrustada] {device_path(root, lrc)}')
            if args.apply:
                lrc.write_text(clean_lrc_text(emb), encoding='utf-8')
    verb = 'hechos' if args.apply else 'pendientes (repite con --apply)'
    print(f'\n{changed} .lrc a limpiar, {created} .lrc a crear: {verb}')
    if args.apply and changed:
        print(f'Copia de los originales en {backup}')
    return 0


# ---------------------------------------------------------------- playlist

def read_list(path):
    """Lista de dicts {title, artists, isrc} desde CSV (con cabecera) o TXT "Titulo - Artista"."""
    text = Path(path).read_text(encoding='utf-8-sig')
    rows = []
    first = text.splitlines()[0] if text.strip() else ''
    if path.lower().endswith('.csv') or (first.count(',') + first.count(';') >= 1 and
                                          re.search(r'(?i)track|title|titulo|artist|isrc', first)):
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        cols = {c.lower().strip(): c for c in reader.fieldnames or []}
        pick = lambda *keys: next((cols[c] for c in cols if any(k in c for k in keys)), None)
        c_title = next((cols[c] for c in cols if c in ('track name', 'title', 'titulo', 'título', 'name', 'cancion', 'canción', 'track')), None) \
            or pick('track name', 'title', 'titulo', 'título', 'song')
        c_artist = pick('artist name', 'artist', 'artista')
        c_isrc = pick('isrc')
        for r in reader:
            rows.append({'title': (r.get(c_title) or '').strip(), 'artists': split_artists(r.get(c_artist) or ''),
                         'artist_raw': (r.get(c_artist) or '').strip(), 'isrc': (r.get(c_isrc) or '').strip().upper() if c_isrc else ''})
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            left, _, right = line.partition(' - ')
            rows.append({'title': left.strip(), 'artists': split_artists(right), 'artist_raw': right.strip(), 'isrc': '',
                         'alt': (right.strip(), split_artists(left))})
    return [r for r in rows if r['title']]


def cmd_playlist(args, cfg):
    root = Path(args.root).resolve()
    lib = []
    for p in audio_files(root, cfg):
        info = read_audio(p) or {'tags': {}, 'seconds': 0}
        title = tag(info, 'TITLE') or p.stem.split(' - ')[0]
        artist = tag(info, 'ARTIST') or (p.stem.split(' - ')[1] if ' - ' in p.stem else '')
        lib.append({'path': p, 'dev': device_path(root, p), 'title': norm(title), 'artists': set(split_artists(artist)),
                    'isrc': tag(info, 'ISRC').upper(), 'label': f'{artist} - {title}', 'secs': int(info.get('seconds') or 0)})
    by_isrc = {x['isrc']: x for x in lib if x['isrc']}
    by_title = defaultdict(list)
    for x in lib:
        by_title[x['title']].append(x)

    def find(t, arts, isrc):
        if isrc and isrc in by_isrc:
            return by_isrc[isrc], 'isrc'
        cands = by_title.get(norm(t), [])
        both = [x for x in cands if x['artists'] & set(arts)]
        if len(both) == 1:
            return both[0], 'exacto'
        if len(cands) == 1 and not both:
            return cands[0], 'solo titulo'
        best, score = None, 0
        key = norm(t) + ' ' + ' '.join(arts)
        for x in lib:
            s = difflib.SequenceMatcher(None, key, x['title'] + ' ' + ' '.join(sorted(x['artists']))).ratio()
            if s > score:
                best, score = x, s
        return (best, f'parecido {score:.0%}') if score >= 0.85 else (None, '')

    rows = read_list(args.input)
    found, missing, doubtful, used = [], [], [], set()
    for r in rows:
        hit, how = find(r['title'], r['artists'], r['isrc'])
        if not hit and r.get('alt'):
            hit, how = find(r['alt'][0], r['alt'][1], '')
        line = f'{r["title"]} - {r["artist_raw"]}'
        if not hit:
            missing.append(line)
            continue
        if hit['dev'] in used:
            continue
        used.add(hit['dev'])
        found.append(hit)
        if how not in ('isrc', 'exacto'):
            doubtful.append(f'{line}  ->  {hit["dev"]}  ({how})')

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', args.name).strip(' .')[:cfg['max_component_chars'] - 5] or 'Playlist'
    out_dir = root / cfg['playlist_dir']
    out_dir.mkdir(parents=True, exist_ok=True)
    nl = '\r\n' if args.crlf else '\n'
    chunks = [found[i:i + cfg['max_tracks']] for i in range(0, len(found), cfg['max_tracks'])] or [[]]
    for k, chunk in enumerate(chunks, 1):
        fname = f'{name}.m3u8' if len(chunks) == 1 else f'{name} {k}.m3u8'
        body = ['#EXTM3U'] + [f'#EXTINF:{x["secs"]},{x["label"]}{nl}{x["dev"]}' for x in chunk]
        (out_dir / fname).write_text(nl.join(body) + nl, encoding='utf-8')
        print(f'Creada {device_path(root, out_dir / fname)} con {len(chunk)} canciones')
    rep = Path(f'{name}_revision.txt')
    rep.write_text('NO ENCONTRADAS (descargalas o revisa el nombre):\n' + '\n'.join(missing or ['(ninguna)']) +
                   '\n\nDUDOSAS (comprueba que es la cancion correcta):\n' + '\n'.join(doubtful or ['(ninguna)']) + '\n',
                   encoding='utf-8')
    print(f'{len(found)} encontradas, {len(missing)} no encontradas, {len(doubtful)} dudosas -> {rep.resolve()}')
    return 0


# ---------------------------------------------------------------- covers

def flac_blocks(data):
    assert data[:4] == b'fLaC'
    p, blocks = 4, []
    while True:
        h = data[p]
        size = int.from_bytes(data[p + 1:p + 4], 'big')
        blocks.append([h & 0x7F, data[p + 4:p + 4 + size]])
        p += 4 + size
        if h & 0x80:
            return blocks, data[p:]


def picture_block(jpeg, w, h):
    mime = b'image/jpeg'
    return (struct.pack('>I', 3) + struct.pack('>I', len(mime)) + mime + struct.pack('>I', 0) +
            struct.pack('>IIIII', w, h, 24, 0, len(jpeg)) + jpeg)


def cmd_covers(args, cfg):
    try:
        from PIL import Image
    except ImportError:
        print('Falta Pillow: pip install pillow')
        return 2
    root, out = Path(args.root).resolve(), Path(args.out).resolve()
    size = args.size or cfg['cover_max_px']
    todo = 0
    for p in audio_files(root, cfg):
        if p.suffix.lower() != '.flac':
            continue
        info = read_flac(p)
        pics = info['pictures'] if info else []
        front = next((x for x in pics if x['type'] == 3), pics[0] if pics else None)
        if not front:
            continue
        j = front['jpeg']
        if j and max(j[0], j[1]) <= size and not j[2]:
            continue
        todo += 1
        print(f'[portada {front["w"]}x{front["h"]} -> {size}px] {device_path(root, p)}')
        if not args.apply:
            continue
        data = p.read_bytes()
        blocks, audio = flac_blocks(data)
        idx = next(i for i, (t, b) in enumerate(blocks) if t == 6 and struct.unpack('>I', b[:4])[0] == front['type'])
        b = blocks[idx][1]
        q = 4
        ml, = struct.unpack('>I', b[q:q + 4]); q += 4 + ml
        dl, = struct.unpack('>I', b[q:q + 4]); q += 4 + dl + 16
        n, = struct.unpack('>I', b[q:q + 4]); q += 4
        img = Image.open(io.BytesIO(b[q:q + n])).convert('RGB')
        img.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=90, progressive=False, optimize=True, subsampling=2)
        blocks[idx][1] = picture_block(buf.getvalue(), img.width, img.height)
        new = bytearray(b'fLaC')
        for i, (t, body) in enumerate(blocks):
            new += bytes([t | (0x80 if i == len(blocks) - 1 else 0)]) + len(body).to_bytes(3, 'big') + body
        new += audio
        dst = out / p.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(new)
        check = read_flac(dst)
        assert check and check['rate'] == info['rate'] and hashlib.sha1(audio).digest() == \
            hashlib.sha1(flac_blocks(new)[1]).digest(), f'verificacion fallida: {dst}'
        lrc = p.with_suffix('.lrc')
        if lrc.exists():
            shutil.copy2(lrc, dst.with_suffix('.lrc'))
    verb = f'copias escritas en {out}' if args.apply else 'pendientes (repite con --apply)'
    print(f'\n{todo} portadas a reducir: {verb}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan'); s.add_argument('root'); s.add_argument('--report')
    s = sub.add_parser('lrc'); s.add_argument('root'); s.add_argument('--apply', action='store_true')
    s = sub.add_parser('playlist'); s.add_argument('root'); s.add_argument('--input', required=True)
    s.add_argument('--name', required=True); s.add_argument('--crlf', action='store_true')
    s = sub.add_parser('covers'); s.add_argument('root'); s.add_argument('--out', required=True)
    s.add_argument('--size', type=int); s.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    cfg = load_config(args.config)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    return {'scan': cmd_scan, 'lrc': cmd_lrc, 'playlist': cmd_playlist, 'covers': cmd_covers}[args.cmd](args, cfg)


if __name__ == '__main__':
    sys.exit(main())
