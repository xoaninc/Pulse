"""Traducción palabra a palabra español → inglés para el buscador (el modelo entiende inglés).

No pretende ser buena traducción: CLIP solo necesita los sustantivos y adjetivos clave, así que
«bolsa de plástico enganchada en un árbol» → «plastic bag caught in a tree» funciona igual de bien.
"""
from __future__ import annotations

import re
import unicodedata

# Expresiones de varias palabras primero (se aplican antes que las sueltas)
FRASES = {
    "bolsa de plastico": "plastic bag", "bolsas de plastico": "plastic bags",
    "botella de plastico": "plastic bottle", "botellas de plastico": "plastic bottles",
    "cables electricos": "power lines", "cable electrico": "power line", "tendido electrico": "power lines",
    "poste electrico": "utility pole", "farola": "street lamp", "senal de trafico": "traffic sign",
    "cono de trafico": "traffic cone", "conos de trafico": "traffic cones", "paso de cebra": "zebra crossing",
    "pintura desconchada": "peeling paint", "pintura descascarillada": "peeling paint",
    "fardos de paja": "hay bales", "balas de paja": "hay bales", "pacas de paja": "hay bales",
    "fardo de paja": "hay bale", "bala de paja": "hay bale", "paca de heno": "hay bale",
    "lena apilada": "stacked firewood", "troncos apilados": "stacked logs", "huellas de neumatico": "tire tracks",
    "huellas de pisadas": "footprints", "rastro de caracol": "snail trail", "tela de arana": "spider web",
    "molinos de viento": "wind turbines", "aerogeneradores": "wind turbines", "aerogenerador": "wind turbine",
    "obra en construccion": "construction site", "contenedor de basura": "dumpster", "papelera": "litter bin",
    "zapatillas colgadas": "sneakers hanging", "colgadas de": "hanging from", "colgado de": "hanging from",
    "en medio de": "in the middle of", "encima de": "on top of", "al lado de": "next to", "dentro de": "inside",
    "a lo lejos": "in the distance", "de noche": "at night", "en la playa": "on the beach",
    "en la calle": "in the street", "en el campo": "in the countryside", "en el monte": "in the mountains",
    "camino de tierra": "dirt road", "sendero": "footpath", "puesta de sol": "sunset",
    "hojas secas": "dry leaves", "hojas caidas": "fallen leaves", "agua estancada": "stagnant water",
    "muro de piedra": "stone wall", "valla metalica": "metal fence", "alambre de espino": "barbed wire",
}

PALABRAS = {
    # objetos y materiales
    "bolsa": "bag", "bolsas": "bags", "plastico": "plastic", "botella": "bottle", "botellas": "bottles",
    "lata": "can", "latas": "cans", "zapatilla": "sneaker", "zapatillas": "sneakers", "zapato": "shoe",
    "zapatos": "shoes", "cable": "cable", "cables": "cables", "cuerda": "rope", "cuerdas": "ropes",
    "globo": "balloon", "globos": "balloons", "cometa": "kite", "bandera": "flag", "banderas": "flags",
    "cinta": "tape", "cintas": "ribbons", "ropa": "clothes", "tendedero": "clothesline", "toalla": "towel",
    "cubo": "bucket", "cubos": "buckets", "barril": "barrel", "bidon": "drum",
    "neumatico": "tire", "neumaticos": "tires", "rueda": "wheel", "palet": "pallet", "palets": "pallets",
    "caja": "box", "cajas": "boxes", "silla": "chair", "sillas": "chairs", "mesa": "table", "banco": "bench",
    "ladrillo": "brick", "ladrillos": "bricks", "teja": "roof tile", "tejas": "roof tiles", "tabla": "board",
    "tablas": "boards", "madera": "wood", "tronco": "log", "troncos": "logs", "lena": "firewood",
    "metal": "metal", "hierro": "iron", "chapa": "metal sheet", "oxido": "rust", "oxidado": "rusty",
    "oxidada": "rusty", "basura": "trash", "escombros": "rubble", "chatarra": "scrap metal", "red": "net",
    "valla": "fence", "verja": "gate", "puerta": "door", "ventana": "window", "persiana": "shutter",
    "pared": "wall", "muro": "wall", "fachada": "facade", "suelo": "ground", "asfalto": "asphalt",
    "acera": "sidewalk", "baldosa": "tile", "baldosas": "tiles", "grafiti": "graffiti", "pintada": "graffiti",
    "pintura": "paint", "mancha": "stain", "manchas": "stains", "grieta": "crack", "grietas": "cracks",
    "agujero": "hole", "agujeros": "holes", "arañazos": "scratches", "aranazos": "scratches", "marca": "mark",
    "marcas": "marks", "huella": "trace", "huellas": "footprints", "pisada": "footprint", "pisadas": "footprints",
    "rastro": "trail", "sombra": "shadow", "sombras": "shadows", "reflejo": "reflection", "reflejos": "reflections",
    "coche": "car", "coches": "cars", "furgoneta": "van", "camion": "truck", "tractor": "tractor",
    "barco": "boat", "barca": "boat", "bicicleta": "bicycle", "andamio": "scaffolding", "grua": "crane",
    "poste": "pole", "postes": "poles", "farolas": "street lamps", "senal": "sign", "cartel": "sign",
    "contenedor": "container", "contenedores": "containers", "maceta": "flower pot", "macetas": "flower pots",
    "estatua": "statue", "escultura": "sculpture", "fuente": "fountain", "columpio": "swing",
    "paja": "straw", "heno": "hay", "fardo": "bale", "fardos": "bales", "ensilado": "silage",
    "arena": "sand", "piedra": "stone", "piedras": "stones", "roca": "rock", "rocas": "rocks", "barro": "mud",
    "polvo": "dust", "nieve": "snow", "hielo": "ice", "agua": "water", "charco": "puddle", "charcos": "puddles",
    "espuma": "foam", "sal": "salt", "polen": "pollen", "musgo": "moss", "liquen": "lichen", "algas": "seaweed",
    # naturaleza y lugares
    "arbol": "tree", "arboles": "trees", "rama": "branch", "ramas": "branches", "hoja": "leaf", "hojas": "leaves",
    "flor": "flower", "flores": "flowers", "hierba": "grass", "cesped": "lawn", "arbusto": "bush",
    "arbustos": "bushes", "zarzal": "bramble", "espinas": "thorns", "campo": "field", "campos": "fields",
    "prado": "meadow", "trigo": "wheat", "arrozal": "rice field", "olivo": "olive tree", "olivos": "olive trees",
    "bosque": "forest", "monte": "hill", "montana": "mountain", "montanas": "mountains", "colina": "hill",
    "valle": "valley", "rio": "river", "arroyo": "stream", "lago": "lake", "mar": "sea", "playa": "beach",
    "costa": "coast", "orilla": "shore", "duna": "dune", "dunas": "dunes", "desierto": "desert",
    "camino": "path", "senda": "trail", "carretera": "road", "calle": "street", "plaza": "square",
    "parque": "park", "jardin": "garden", "huerto": "vegetable garden", "solar": "vacant lot", "obra": "construction site",
    "fabrica": "factory", "nave": "warehouse", "granja": "farm", "pueblo": "village", "ciudad": "city",
    "estacion": "station", "via": "railway track", "vias": "railway tracks", "puente": "bridge", "tunel": "tunnel",
    "cielo": "sky", "nube": "cloud", "nubes": "clouds", "niebla": "fog", "lluvia": "rain", "viento": "wind",
    "sol": "sun", "luz": "light", "noche": "night", "atardecer": "sunset", "amanecer": "sunrise",
    # seres animados
    "persona": "person", "personas": "people", "gente": "people", "hombre": "man", "mujer": "woman",
    "nino": "child", "ninos": "children", "perro": "dog", "perros": "dogs", "gato": "cat", "gatos": "cats",
    "pajaro": "bird", "pajaros": "birds", "paloma": "pigeon", "palomas": "pigeons", "gaviota": "seagull",
    "gaviotas": "seagulls", "cabra": "goat", "cabras": "goats", "oveja": "sheep", "ovejas": "sheep",
    "vaca": "cow", "vacas": "cows", "caballo": "horse", "caballos": "horses", "cangrejo": "crab",
    "cangrejos": "crabs", "caracol": "snail", "caracoles": "snails", "lagartija": "lizard", "mariposa": "butterfly",
    "hormigas": "ants", "arana": "spider", "pato": "duck", "patos": "ducks", "cigüena": "stork", "ciguena": "stork",
    # adjetivos y verbos útiles
    "roto": "broken", "rota": "broken", "rotos": "broken", "rotas": "broken", "doblado": "bent", "doblada": "bent",
    "torcido": "twisted", "aplastado": "crushed", "abandonado": "abandoned", "abandonada": "abandoned",
    "viejo": "old", "vieja": "old", "nuevo": "new", "solo": "alone", "sola": "alone", "aislado": "isolated",
    "aislada": "isolated", "apilado": "stacked", "apilados": "stacked", "apiladas": "stacked", "amontonado": "piled",
    "amontonados": "piled", "monton": "pile", "montones": "piles", "pila": "pile", "fila": "row", "filas": "rows",
    "colgado": "hanging", "colgada": "hanging", "colgados": "hanging", "colgadas": "hanging",
    "enganchado": "caught", "enganchada": "caught", "enganchadas": "caught", "enredado": "tangled",
    "enredados": "tangled", "volando": "flying", "flotando": "floating", "tirado": "dumped", "tirada": "dumped",
    "esparcido": "scattered", "esparcidos": "scattered", "desconchado": "peeling", "desconchada": "peeling",
    "quemado": "burnt", "seco": "dry", "seca": "dry", "mojado": "wet", "verde": "green", "rojo": "red",
    "roja": "red", "azul": "blue", "amarillo": "yellow", "amarilla": "yellow", "blanco": "white",
    "blanca": "white", "negro": "black", "negra": "black", "naranja": "orange", "rosa": "pink",
    "grande": "big", "pequeno": "small", "pequena": "small", "muchos": "many", "muchas": "many",
    # palabras de enlace
    "de": "of", "del": "of the", "en": "in", "con": "with", "sin": "without", "sobre": "on", "bajo": "under",
    "entre": "among", "y": "and", "o": "or", "un": "a", "una": "a", "unos": "some", "unas": "some",
    "el": "the", "la": "the", "los": "the", "las": "the", "al": "to the", "por": "through", "junto": "next to",
}


def _sin_acentos(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c)).replace("ñ", "n")


def parece_espanol(q: str) -> bool:
    palabras = re.findall(r"[a-záéíóúñü]+", q.lower())
    if any(c in q.lower() for c in "áéíóúñ¿¡"):
        return True
    es = sum(1 for p in palabras if _sin_acentos(p) in PALABRAS and PALABRAS[_sin_acentos(p)] != _sin_acentos(p))
    return es >= max(1, len(palabras) // 2)


def a_ingles(q: str) -> str:
    """Devuelve la consulta en inglés si parece española; si no, tal cual."""
    if not parece_espanol(q):
        return q
    t = " " + _sin_acentos(q) + " "
    for es, en in sorted(FRASES.items(), key=lambda x: -len(x[0])):
        t = t.replace(f" {es} ", f" {en} ")
    out = []
    for p in t.split():
        out.append(PALABRAS.get(p, p))
    texto = " ".join(out)
    # «bag of plastic» → «plastic bag» y similares (sustantivo de material)
    texto = re.sub(r"\b(\w+) of (plastic|wood|metal|stone|iron|straw|hay|paper)\b", r"\2 \1", texto)
    texto = re.sub(r"\bhanging of\b", "hanging from", texto)
    return "a photo of " + texto.strip()
