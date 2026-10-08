"""Provincias de España con su código INE (el mismo que usan BOE y Seguridad Social)."""

from __future__ import annotations

from .textutil import norm, slugify

PROVINCIAS: dict[str, str] = {
    "01": "Araba/Álava", "02": "Albacete", "03": "Alicante/Alacant", "04": "Almería",
    "05": "Ávila", "06": "Badajoz", "07": "Illes Balears", "08": "Barcelona",
    "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón/Castelló",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca",
    "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
    "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia",
    "35": "Las Palmas", "36": "Pontevedra", "37": "Salamanca",
    "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia",
    "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia/València", "47": "Valladolid", "48": "Bizkaia",
    "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}

CCAA_PROVINCIAS: dict[str, list[str]] = {
    "Andalucía": ["04", "11", "14", "18", "21", "23", "29", "41"],
    "Aragón": ["22", "44", "50"],
    "Asturias": ["33"],
    "Illes Balears": ["07"],
    "Canarias": ["35", "38"],
    "Cantabria": ["39"],
    "Castilla y León": ["05", "09", "24", "34", "37", "40", "42", "47", "49"],
    "Castilla-La Mancha": ["02", "13", "16", "19", "45"],
    "Cataluña": ["08", "17", "25", "43"],
    "Comunitat Valenciana": ["03", "12", "46"],
    "Extremadura": ["06", "10"],
    "Galicia": ["15", "27", "32", "36"],
    "Comunidad de Madrid": ["28"],
    "Región de Murcia": ["30"],
    "Navarra": ["31"],
    "País Vasco": ["01", "20", "48"],
    "La Rioja": ["26"],
    "Ceuta": ["51"],
    "Melilla": ["52"],
}
CCAA_DE: dict[str, str] = {cod: ccaa for ccaa, cods in CCAA_PROVINCIAS.items() for cod in cods}

# Nombres alternativos que aparecen en las webs (castellano / lengua cooficial / sin tilde).
_ALIAS: dict[str, str] = {
    "alava": "01", "araba": "01", "alicante": "03", "alacant": "03",
    "baleares": "07", "illes balears": "07", "islas baleares": "07", "balears": "07",
    "castellon": "12", "castello": "12", "coruna": "15", "a coruna": "15", "la coruna": "15",
    "guipuzcoa": "20", "gipuzkoa": "20", "lerida": "25", "lleida": "25", "gerona": "17",
    "orense": "32", "ourense": "32", "vizcaya": "48", "bizkaia": "48", "valencia": "46",
    "tenerife": "38", "santa cruz de tenerife": "38", "las palmas": "35",
    "gran canaria": "35", "navarra": "31", "nafarroa": "31", "asturias": "33",
    "principado de asturias": "33", "rioja": "26", "la rioja": "26", "murcia": "30",
    "madrid": "28",
}


def _variants(name: str) -> list[str]:
    return [norm(p) for p in name.split("/")]


_BY_NAME: dict[str, str] = {}
for _cod, _name in PROVINCIAS.items():
    for _v in _variants(_name):
        _BY_NAME[_v] = _cod
_BY_NAME.update(_ALIAS)


def province_code(value: str | int | None) -> str | None:
    """Devuelve el código INE ('28') a partir de un código o nombre de provincia."""
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        code = text.zfill(2)
        return code if code in PROVINCIAS else None
    n = norm(text)
    n = n.removesuffix(" provincia").removeprefix("provincia de ")
    if n in _BY_NAME:
        return _BY_NAME[n]
    # 'Alicante/Alacant', 'Málaga (Málaga)', 'Madrid, Madrid' -> probar cada parte
    for part in reversed([p.strip(" ()") for p in n.replace("(", ",").replace("/", ",").split(",")]):
        if part in _BY_NAME:
            return _BY_NAME[part]
    return None


def province_name(code: str) -> str:
    return PROVINCIAS.get(code, code)


def province_slug(code: str) -> str:
    """Slug 'web' de la provincia (primera variante del nombre): 'alicante', 'a-coruna'..."""
    return slugify(PROVINCIAS[code].split("/")[0])


def province_slugs(code: str) -> list[str]:
    """Todas las formas 'slug' con las que una web puede nombrar la provincia."""
    names = PROVINCIAS[code].split("/") + [a for a, c in _ALIAS.items() if c == code]
    return list(dict.fromkeys(slugify(n) for n in names))


def ccaa_slug(code: str) -> str:
    return slugify(CCAA_DE.get(code, ""))


def resolve_provinces(values) -> list[str]:
    """Convierte una lista de códigos/nombres/CCAA en códigos INE. Vacío o 'todas' = todas."""
    if not values or (isinstance(values, str) and norm(values) in {"todas", "all", "*"}):
        return list(PROVINCIAS)
    if isinstance(values, (str, int)):
        values = [values]
    out: list[str] = []
    ccaa_norm = {norm(k): v for k, v in CCAA_PROVINCIAS.items()}
    for v in values:
        code = province_code(v)
        if code:
            out.append(code)
            continue
        if norm(str(v)) in ccaa_norm:
            out.extend(ccaa_norm[norm(str(v))])
            continue
        raise ValueError(f"Provincia o comunidad desconocida: {v!r}")
    return list(dict.fromkeys(out))
