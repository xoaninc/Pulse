"""Segundo filtro OPCIONAL con un modelo de visión en la nube (Groq u otro compatible con OpenAI).

Solo se usa si pones una clave en el archivo `ia.env` (ver README). Se envían únicamente
miniaturas pequeñas (512 px) de las candidatas que tú pidas revisar, nunca la fototeca.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import imagenes, rutas

URL_DEFECTO = "https://api.groq.com/openai/v1"
# Único modelo con visión de Groq a finales de 2026: máximo 3 imágenes por petición y
# 2.048 tokens por imagen sea cual sea su tamaño (por eso basta con 768 px).
MODELO_DEFECTO = "qwen/qwen3.8-27b"
IMAGENES_POR_PETICION = 3
LADO_IMAGEN = 768
NOTAS = rutas.DATOS / "ia_notas.json"


def _ficheros_env() -> list:
    return [f for f in (rutas.RAIZ / n for n in ("ia.env", "ia.env.txt", "ia.env.rtf", ".env")) if f.exists()]


def _config() -> dict:
    """Lee la clave de ia.env (o del entorno). Tolerante: acepta «export», comillas, espacios,
    ficheros guardados por TextEdit (.txt o .rtf) y, en último caso, cualquier gsk_… del texto."""
    cfg = {"clave": None, "url": URL_DEFECTO, "modelo": MODELO_DEFECTO}
    valores: dict[str, str] = {}
    sueltas: list[str] = []
    for fichero in _ficheros_env():
        try:
            texto = fichero.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for ln in texto.splitlines():
            ln = ln.strip().removeprefix("export ").strip()
            m = re.match(r"^([A-Z_]+)\s*=\s*(.+?)\s*\\?$", ln)
            if m:
                valores.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'").strip())
        sueltas += re.findall(r"gsk_[A-Za-z0-9]{20,}", texto)
    get = lambda *ks: next((valores.get(k) or os.environ.get(k) for k in ks if valores.get(k) or os.environ.get(k)), None)  # noqa: E731
    cfg["clave"] = get("ARTE_IA_CLAVE", "GROQ_API_KEY") or (sueltas[0] if sueltas else None)
    cfg["url"] = (get("ARTE_IA_URL") or URL_DEFECTO).rstrip("/")
    cfg["modelo"] = get("ARTE_IA_MODELO") or MODELO_DEFECTO
    return cfg


def problema() -> str | None:
    """Si hay un ia.env pero no se ha encontrado ninguna clave, explica por qué."""
    if _config()["clave"] or not _ficheros_env():
        return None
    return ("Hay un archivo ia.env pero no encuentro la clave. Créalo desde la Terminal, en la carpeta del "
            "proyecto, con:  echo 'GROQ_API_KEY=gsk_TU_CLAVE' > ia.env   y vuelve a abrir la galería.")


def disponible() -> dict | None:
    c = _config()
    return {"modelo": c["modelo"], "url": c["url"]} if c["clave"] else None


def leer_notas() -> dict:
    try:
        return json.loads(NOTAS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_notas(n: dict) -> None:
    NOTAS.parent.mkdir(parents=True, exist_ok=True)
    NOTAS.write_text(json.dumps(n, ensure_ascii=False, indent=1), encoding="utf-8")


def ajuste(nota: dict | None) -> float:
    """Cuánto sube o baja una candidata según la nota (0-10) del modelo."""
    if not nota or "nota" not in nota:
        return 0.0
    try:
        return (float(nota["nota"]) - 5.0) * 0.45
    except Exception:
        return 0.0


def _pedir(cfg: dict, mensajes: list, max_tokens: int = 900, aviso=print) -> str:
    peticion = {
        "model": cfg["modelo"],
        "messages": mensajes,
        "temperature": 0.2,
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if "groq.com" in cfg["url"]:
        peticion["reasoning_effort"] = "none"  # respuesta directa, sin «pensar» (más rápido y barato)
    cuerpo = json.dumps(peticion).encode()
    for intento in range(6):
        req = urllib.request.Request(
            cfg["url"] + "/chat/completions", data=cuerpo, method="POST",
            headers={"Authorization": f"Bearer {cfg['clave']}", "Content-Type": "application/json",
                     "User-Agent": "arte-involuntario/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="ignore")[:300]
            if e.code in (429, 500, 502, 503) and intento < 5:
                espera = float(e.headers.get("retry-after") or 2 ** intento * 3)
                aviso(f"  (límite de la API, espero {espera:.0f} s…)")
                time.sleep(min(espera, 60))
                continue
            if e.code == 400 and intento < 5:
                d = json.loads(cuerpo)
                quitado = False
                for clave in ("reasoning_effort", "response_format"):
                    if clave in txt and clave in d:
                        d.pop(clave)
                        quitado = True
                if quitado:
                    cuerpo = json.dumps(d).encode()
                    continue
            if e.code in (401, 403):
                raise RuntimeError("La clave de la IA no es válida (revisa ia.env).") from e
            raise RuntimeError(f"La API respondió {e.code}: {txt}") from e
        except urllib.error.URLError as e:
            if intento < 3:
                time.sleep(3)
                continue
            raise RuntimeError(f"No hay conexión con {cfg['url']}: {e}") from e
    raise RuntimeError("La API no respondió")


def _json_de(texto: str):
    try:
        return json.loads(texto)
    except Exception:
        m = re.search(r"\{.*\}", texto, re.S)
        return json.loads(m.group(0)) if m else {}


def _imagen_b64(ruta: str, lado: int = LADO_IMAGEN) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(imagenes.miniatura_jpeg(ruta, lado, 80)).decode()


def revisar_categoria(cat: str, candidatas: list[dict], cfg_cat: dict, ix, aviso=print) -> dict:
    c = _config()
    if not c["clave"]:
        raise RuntimeError("No hay clave de IA. Crea el archivo ia.env (mira el README).")
    info = next(x for x in cfg_cat["categorias"] if x["id"] == cat)
    otras = ", ".join(x["nombre"] for x in cfg_cat["categorias"] if x["id"] != cat)
    sistema = (
        "Eres profesor de paisajismo y conoces a fondo el «Breve tratado del arte involuntario» de Gilles Clément. "
        "Arte involuntario: el feliz resultado de una combinación imprevista de situaciones u objetos organizados "
        "conforme a reglas de armonía dictadas por el azar; accidentes menores y furtivos donde la naturaleza se "
        "cruza con huellas humanas; nunca grandes paisajes turísticos ni obras de arte deliberadas. "
        f"Evalúas fotos para la categoría «{info['nombre']}»: {info.get('definicion', '')} "
        f"Otras categorías posibles: {otras}. Responde SOLO con JSON."
    )
    notas: dict = {}
    trozos = [candidatas[i:i + IMAGENES_POR_PETICION] for i in range(0, len(candidatas), IMAGENES_POR_PETICION)]
    for k, trozo in enumerate(trozos, 1):
        aviso(f"  IA · {info['nombre']}: lote {k}/{len(trozos)}")
        contenido = [{"type": "text", "text": (
            f"Te paso {len(trozo)} fotos numeradas del 1 al {len(trozo)}. Para cada una di si es un buen ejemplo de "
            f"«{info['nombre']}» de Clément. Devuelve {{\"fotos\": [{{\"n\": 1, \"nota\": 0-10, "
            "\"mejor_categoria\": \"...\", \"motivo\": \"frase corta en español\", \"pie\": \"descripción breve de lo que se ve, "
            "estilo pie de foto de Clément\"}}]}}. Sé exigente: 8-10 solo si encaja claramente."
        )}]
        validas = []
        for d in trozo:
            f = ix.foto(d["uuid"])
            if not f or not f.get("ruta_analisis"):
                continue
            validas.append(d["uuid"])
            contenido.append({"type": "text", "text": f"Foto {len(validas)}:"})
            contenido.append({"type": "image_url", "image_url": {"url": _imagen_b64(f["ruta_analisis"])}})
        if not validas:
            continue
        try:
            r = _json_de(_pedir(c, [{"role": "system", "content": sistema}, {"role": "user", "content": contenido}], aviso=aviso))
        except Exception as e:
            aviso(f"  ! {e}")
            continue
        for item in r.get("fotos", []):
            try:
                u = validas[int(item["n"]) - 1]
            except Exception:
                continue
            notas[u] = {k2: item.get(k2) for k2 in ("nota", "mejor_categoria", "motivo", "pie")}
    return notas


def frases_paseo(fotos: list[dict], ix, aviso=print) -> dict:
    """Propone, para cada foto del paseo, una frase sobria al estilo Fulton y una palabra."""
    c = _config()
    if not c["clave"]:
        raise RuntimeError("No hay clave de IA. Crea el archivo ia.env (mira el README).")
    sistema = (
        "Ayudas a un estudiante a rotular un paseo fotográfico al estilo de Hamish Fulton: bajo cada foto, una frase "
        "breve y sobria, en presente y en español, que nombre un suceso singular del momento (algo que se ve, se oye o "
        "se siente: un animal, el viento, una nube, un cruce, una sombra). Nada de adjetivos grandilocuentes. "
        "Responde SOLO con JSON."
    )
    out: dict = {}
    trozos = [fotos[i:i + IMAGENES_POR_PETICION] for i in range(0, len(fotos), IMAGENES_POR_PETICION)]
    for k, trozo in enumerate(trozos, 1):
        aviso(f"  IA · frases del paseo: lote {k}/{len(trozos)}")
        contenido = [{"type": "text", "text": (
            "Para cada foto devuelve {\"fotos\": [{\"n\": 1, \"frase\": \"...\", \"palabra\": \"UNA PALABRA EN MAYÚSCULAS\"}]}. "
            "Ten en cuenta la hora y el km si te los doy."
        )}]
        validas = []
        for d in trozo:
            f = ix.foto(d["uuid"])
            if not f or not f.get("ruta_analisis"):
                continue
            validas.append(d["uuid"])
            extra = " · ".join(x for x in (d.get("hora"), f"km {d['km']}" if d.get("km") is not None else "") if x)
            contenido.append({"type": "text", "text": f"Foto {len(validas)} ({extra}):"})
            contenido.append({"type": "image_url", "image_url": {"url": _imagen_b64(f["ruta_analisis"])}})
        if not validas:
            continue
        try:
            r = _json_de(_pedir(c, [{"role": "system", "content": sistema}, {"role": "user", "content": contenido}], aviso=aviso))
        except Exception as e:
            aviso(f"  ! {e}")
            continue
        for item in r.get("fotos", []):
            try:
                out[validas[int(item["n"]) - 1]] = {"frase": item.get("frase", ""), "palabra": item.get("palabra", "")}
            except Exception:
                continue
    return out
