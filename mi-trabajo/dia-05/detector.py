"""Detecta texto oculto y contenido sospechoso en los CV de práctica."""

import re
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree


def buscar_raiz():
    for carpeta in Path(__file__).resolve().parents:
        if (carpeta / "datos" / "dia-05" / "reclutamiento").is_dir():
            return carpeta
    raise FileNotFoundError("No encontré datos/dia-05/reclutamiento/.")


RAIZ = buscar_raiz()
CARPETA_CVS = RAIZ / "datos" / "dia-05" / "reclutamiento"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PATRON_SISTEMA = re.compile(
    r"\b(al|para el|para la|a la)\s+(sistema|asistente|agente|ia|programa)\b"
    r"|\b(system|assistant|agent)\s*[:,]"
    r"|\b(ignore|disregard|override|ignora|omite|olvida)\s+"
    r"(your|the|tus|las|sus|all|previous|prior|instrucciones|reglas)\b"
    r"|\b(si eres|if you are)\s+(un|una|a|an)?\s*"
    r"(sistema|asistente|agente|system|assistant|agent)\b",
    re.IGNORECASE,
)
PATRON_AVAL = re.compile(
    r"\b(preaprob\w*|preseleccionad\w*|aprobado|aprobada|validado|validada|"
    r"referid[oa] por|recomendad[oa] por|visto bueno|evaluaci[oó]n|"
    r"prioridad alta|primer lugar|avanzar a oferta)\b",
    re.IGNORECASE,
)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def lineas_sospechosas(texto):
    frases = re.split(r"(?<=[.!?])\s+|\n+", texto)
    return [frase.strip() for frase in frases if PATRON_SISTEMA.search(normalizar(frase))]


def _nuevo_hallazgo(hallazgos, tipo, donde, texto, por_que):
    hallazgos.append({
        "tipo": tipo,
        "donde": donde,
        "texto": texto.strip(),
        "por_que": por_que,
    })


def _texto_nodo(nodo):
    partes = []
    for elemento in nodo.iter():
        if elemento.tag == W + "t" and elemento.text:
            partes.append(elemento.text)
        elif elemento.tag == W + "tab":
            partes.append("\t")
        elif elemento.tag == W + "br":
            partes.append("\n")
    return "".join(partes)


def _motivo_oculto(run):
    propiedades = run.find(W + "rPr")
    if propiedades is None:
        return None
    if propiedades.find(W + "vanish") is not None or propiedades.find(W + "webHidden") is not None:
        return "marcado como oculto"
    color = propiedades.find(W + "color")
    if color is not None:
        valor = color.get(W + "val", "").strip().lstrip("#")
        if re.fullmatch(r"[0-9a-fA-F]{6}", valor):
            rgb = tuple(int(valor[i:i + 2], 16) for i in (0, 2, 4))
            if min(rgb) >= 245:
                return "color casi blanco"
    tamano = propiedades.find(W + "sz")
    if tamano is not None:
        try:
            if float(tamano.get(W + "val", "100")) <= 12:
                return "letra de 6 puntos o menos"
        except ValueError:
            pass
    return None


def _leer_docx(ruta):
    hallazgos = []
    texto_visible = []
    with zipfile.ZipFile(ruta) as archivo:
        nombres = set(archivo.namelist())
        xml = ElementTree.fromstring(archivo.read("word/document.xml"))
        for numero, parrafo in enumerate(xml.iter(W + "p"), start=1):
            partes_visibles = []
            grupo_oculto = []
            motivos_grupo = set()

            def guardar_grupo():
                if grupo_oculto:
                    motivo = ", ".join(sorted(motivos_grupo))
                    _nuevo_hallazgo(
                        hallazgos, "texto oculto", f"párrafo {numero}",
                        "".join(grupo_oculto),
                        f"Está {motivo}; se cuenta como un solo escondite aunque Word lo divida en varios fragmentos.",
                    )
                    grupo_oculto.clear()
                    motivos_grupo.clear()

            for run in parrafo.iter(W + "r"):
                texto_run = _texto_nodo(run)
                if not texto_run:
                    continue
                motivo = _motivo_oculto(run)
                if motivo:
                    if not grupo_oculto:
                        partes_visibles.append(" ")
                    grupo_oculto.append(texto_run)
                    motivos_grupo.add(motivo)
                else:
                    guardar_grupo()
                    partes_visibles.append(texto_run)
            guardar_grupo()
            texto_parrafo = "".join(partes_visibles).strip()
            if texto_parrafo:
                texto_visible.append(texto_parrafo)
                for frase in lineas_sospechosas(texto_parrafo):
                    _nuevo_hallazgo(
                        hallazgos, "frase dirigida a un sistema", f"párrafo {numero}",
                        frase, "El texto visible se dirige a un sistema o le pide cambiar sus instrucciones.",
                    )

        if "word/comments.xml" in nombres:
            comentarios = ElementTree.fromstring(archivo.read("word/comments.xml"))
            for comentario in comentarios.findall(W + "comment"):
                texto = "\n".join(_texto_nodo(p) for p in comentario.findall(".//" + W + "p")).strip()
                if texto:
                    _nuevo_hallazgo(
                        hallazgos, "comentario", f"comentario {comentario.get(W + 'id', '?')}",
                        texto, "El contenido está en un comentario, fuera del texto normal que ve quien lee el CV.",
                    )

        for nombre in ("docProps/core.xml", "docProps/custom.xml"):
            if nombre not in nombres:
                continue
            propiedades = ElementTree.fromstring(archivo.read(nombre))
            for propiedad in propiedades:
                texto = "".join(propiedad.itertext()).strip()
                if texto and (PATRON_SISTEMA.search(normalizar(texto)) or PATRON_AVAL.search(texto)):
                    campo = propiedad.tag.split("}")[-1]
                    _nuevo_hallazgo(
                        hallazgos, "propiedad del archivo", f"{nombre}, campo {campo}",
                        texto, "El metadato contiene una instrucción para el sistema o un aval/evaluación que no se puede comprobar.",
                    )

    return "\n".join(texto_visible), hallazgos


def _leer_cadena_pdf(datos, indice):
    if datos[indice:indice + 1] == b"<":
        fin = datos.find(b">", indice + 1)
        if fin < 0:
            return b"", len(datos)
        hexadecimal = re.sub(rb"\s", b"", datos[indice + 1:fin])
        if len(hexadecimal) % 2:
            hexadecimal += b"0"
        try:
            return bytes.fromhex(hexadecimal.decode("ascii")), fin + 1
        except ValueError:
            return b"", fin + 1

    salida = bytearray()
    nivel = 1
    indice += 1
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while indice < len(datos):
        byte = datos[indice]
        if byte == ord("\\"):
            indice += 1
            if indice >= len(datos):
                break
            siguiente = datos[indice]
            if siguiente in escapes:
                salida.append(escapes[siguiente])
            elif 48 <= siguiente <= 55:
                octal = re.match(rb"[0-7]{1,3}", datos[indice:indice + 3])
                if octal:
                    salida.append(int(octal.group(), 8) & 0xFF)
                    indice += len(octal.group()) - 1
            elif siguiente not in (10, 13):
                salida.append(siguiente)
        elif byte == ord("("):
            nivel += 1
            salida.append(byte)
        elif byte == ord(")"):
            nivel -= 1
            if nivel == 0:
                return bytes(salida), indice + 1
            salida.append(byte)
        else:
            salida.append(byte)
        indice += 1
    return bytes(salida), indice


def _decodificar_pdf(datos):
    if datos.startswith(b"\xfe\xff"):
        return datos[2:].decode("utf-16-be", errors="replace")
    return datos.decode("cp1252", errors="replace")


def _tokens_pdf(datos):
    indice = 0
    while indice < len(datos):
        byte = datos[indice]
        if byte in b"\x00\t\n\f\r ":
            indice += 1
            continue
        if byte == ord("%"):
            fin = datos.find(b"\n", indice)
            indice = len(datos) if fin < 0 else fin + 1
            continue
        if byte == ord("("):
            valor, indice = _leer_cadena_pdf(datos, indice)
            yield "cadena", _decodificar_pdf(valor)
            continue
        if byte == ord("<"):
            if datos[indice:indice + 2] == b"<<":
                indice += 2
                continue
            valor, indice = _leer_cadena_pdf(datos, indice)
            yield "cadena", _decodificar_pdf(valor)
            continue
        if byte == ord(">") and datos[indice:indice + 2] == b">>":
            indice += 2
            continue
        if byte in (ord("["), ord("]")):
            yield chr(byte), chr(byte)
            indice += 1
            continue
        if byte == ord("/"):
            fin = indice + 1
            while fin < len(datos) and datos[fin] not in b"\x00\t\n\f\r ()<>[]{}/%":
                fin += 1
            yield "nombre", datos[indice + 1:fin].decode("latin-1", errors="replace")
            indice = fin
            continue
        fin = indice
        while fin < len(datos) and datos[fin] not in b"\x00\t\n\f\r ()<>[]{}/%":
            fin += 1
        if fin == indice:
            indice += 1
            continue
        palabra = datos[indice:fin].decode("latin-1", errors="replace")
        try:
            yield "numero", float(palabra)
        except ValueError:
            yield "operador", palabra
        indice = fin


def _flujos_pdf(datos):
    for numero, inicio in enumerate(re.finditer(rb"(?<!end)stream\r?\n", datos), start=1):
        fin = datos.find(b"endstream", inicio.end())
        if fin < 0:
            continue
        contenido = datos[inicio.end():fin].rstrip(b"\r\n")
        encabezado = datos[max(0, datos.rfind(b"obj", 0, inicio.start())):inicio.start()]
        if b"/FlateDecode" in encabezado:
            try:
                contenido = zlib.decompress(contenido)
            except zlib.error:
                try:
                    contenido = zlib.decompress(contenido, -zlib.MAX_WBITS)
                except zlib.error:
                    continue
        yield numero, contenido


def _es_blanco(color):
    return color is not None and len(color) == 3 and min(color) >= 0.96


def _leer_contenido_pdf(contenido, numero_flujo):
    visibles = []
    ocultos = []
    operandos = []
    tamano_letra = 12.0
    modo_texto = 0
    color_relleno = (0.0, 0.0, 0.0)
    color_trazo = (0.0, 0.0, 0.0)
    bloque = []
    motivo_bloque = None

    def cerrar_bloque():
        nonlocal motivo_bloque
        if bloque:
            ocultos.append((f"flujo {numero_flujo}", "".join(bloque), motivo_bloque))
            visibles.append(" ")
            bloque.clear()
            motivo_bloque = None

    for tipo, valor in _tokens_pdf(contenido):
        if tipo != "operador":
            operandos.append((tipo, valor))
            continue

        numeros = [v for t, v in operandos if t == "numero"]
        cadenas = [v for t, v in operandos if t == "cadena"]
        if valor == "Tf" and numeros:
            tamano_letra = numeros[-1]
        elif valor == "Tr" and numeros:
            modo_texto = int(numeros[-1])
        elif valor in ("g", "G") and numeros:
            gris = numeros[-1]
            color = (gris, gris, gris)
            if valor == "g":
                color_relleno = color
            else:
                color_trazo = color
        elif valor in ("rg", "RG") and len(numeros) >= 3:
            color = tuple(numeros[-3:])
            if valor == "rg":
                color_relleno = color
            else:
                color_trazo = color
        elif valor in ("k", "K") and len(numeros) >= 4:
            cian, magenta, amarillo, negro = numeros[-4:]
            color = ((1 - cian) * (1 - negro), (1 - magenta) * (1 - negro),
                     (1 - amarillo) * (1 - negro))
            if valor == "k":
                color_relleno = color
            else:
                color_trazo = color

        if valor in ("Tj", "TJ", "'", '"') and cadenas:
            texto = "".join(cadenas)
            usa_relleno = modo_texto in (0, 2, 4, 6)
            usa_trazo = modo_texto in (1, 2, 5, 6)
            blanco = (usa_relleno and _es_blanco(color_relleno)) or (usa_trazo and _es_blanco(color_trazo))
            if modo_texto in (3, 7):
                motivo = "modo de texto PDF invisible"
            elif blanco:
                motivo = "texto blanco sobre fondo claro"
            elif 0 < tamano_letra <= 4:
                motivo = f"letra diminuta ({tamano_letra:g} puntos)"
            else:
                motivo = None
            if motivo:
                if motivo_bloque and motivo_bloque != motivo:
                    cerrar_bloque()
                bloque.append(texto)
                motivo_bloque = motivo
            else:
                cerrar_bloque()
                visibles.append(" " + texto)
        elif bloque:
            cerrar_bloque()
        operandos = []

    cerrar_bloque()
    return "".join(visibles).strip(), ocultos


def _leer_pdf(ruta):
    datos = ruta.read_bytes()
    hallazgos = []
    partes_visibles = []
    ocultos = []
    for numero, contenido in _flujos_pdf(datos):
        texto, bloques_ocultos = _leer_contenido_pdf(contenido, numero)
        if texto.strip():
            partes_visibles.append(texto)
        ocultos.extend(bloques_ocultos)

    for ubicacion, texto, motivo in ocultos:
        _nuevo_hallazgo(
            hallazgos, "texto oculto", ubicacion, texto,
            f"El contenido es {motivo}; se agruparon los fragmentos contiguos como un solo escondite.",
        )

    texto_visible = "\n".join(partes_visibles)
    for frase in lineas_sospechosas(texto_visible):
        _nuevo_hallazgo(
            hallazgos, "frase dirigida a un sistema", "texto visible del PDF",
            frase, "El texto visible se dirige a un sistema o le pide cambiar sus instrucciones.",
        )

    campos = (b"Title", b"Author", b"Subject", b"Keywords")
    for campo in campos:
        patron = rb"/" + campo + rb"\s*([(<])"
        for coincidencia in re.finditer(patron, datos):
            valor, _ = _leer_cadena_pdf(datos, coincidencia.start(1))
            texto = _decodificar_pdf(valor).strip()
            if texto and (PATRON_SISTEMA.search(normalizar(texto)) or PATRON_AVAL.search(texto)):
                _nuevo_hallazgo(
                    hallazgos, "propiedad del archivo", f"metadato PDF /{campo.decode()}",
                    texto, "El metadato contiene una instrucción para el sistema o un aval/evaluación que no se puede comprobar.",
                )

    for coincidencia in re.finditer(rb"/Contents\s*([(<])", datos):
        valor, _ = _leer_cadena_pdf(datos, coincidencia.start(1))
        texto = _decodificar_pdf(valor).strip()
        if texto:
            _nuevo_hallazgo(
                hallazgos, "comentario/anotación PDF", "campo /Contents",
                texto, "El contenido está guardado como anotación, fuera del texto normal que ve quien lee el CV.",
            )

    return texto_visible, hallazgos


def revisar(ruta):
    """Devuelve archivo y hallazgos; cada elemento representa un escondite."""
    ruta = Path(ruta).resolve()
    if ruta.parent != CARPETA_CVS.resolve() or not ruta.is_file():
        raise ValueError("Solo puedo revisar currículums de datos/dia-05/reclutamiento/.")
    if ruta.suffix.lower() == ".docx":
        _, hallazgos = _leer_docx(ruta)
    elif ruta.suffix.lower() == ".pdf":
        _, hallazgos = _leer_pdf(ruta)
    else:
        raise ValueError("Solo reviso archivos .docx y .pdf.")
    return {"archivo": ruta.name, "hallazgos": hallazgos}


def texto_visible(ruta):
    """Regresa solo el texto visible; omite ocultos, comentarios y metadatos."""
    ruta = Path(ruta).resolve()
    if ruta.parent != CARPETA_CVS.resolve() or not ruta.is_file():
        raise ValueError("Solo puedo leer currículums de datos/dia-05/reclutamiento/.")
    if ruta.suffix.lower() == ".docx":
        texto, _ = _leer_docx(ruta)
    elif ruta.suffix.lower() == ".pdf":
        texto, _ = _leer_pdf(ruta)
    else:
        raise ValueError("Solo leo archivos .docx y .pdf.")
    return texto


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    total = 0
    archivos = sorted(
        ruta for ruta in CARPETA_CVS.iterdir()
        if ruta.suffix.lower() in (".docx", ".pdf")
    )
    for ruta in archivos:
        resultado = revisar(ruta)
        print(f"{resultado['archivo']}:")
        if not resultado["hallazgos"]:
            print("  Sin hallazgos.")
            continue
        for indice, hallazgo in enumerate(resultado["hallazgos"], start=1):
            total += 1
            print(f"  {indice}. {hallazgo['tipo']} — {hallazgo['donde']}")
            print(f"     Por qué: {hallazgo['por_que']}")
            print(f"     Contenido: {hallazgo['texto']}")
    print(f"\nTotal: {total} trampa(s)")


if __name__ == "__main__":
    main()
