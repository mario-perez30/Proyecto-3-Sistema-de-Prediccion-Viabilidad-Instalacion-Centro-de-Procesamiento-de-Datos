"""Genera el documento de entrega en Word a partir de los Markdown de ``docs/``.

Uso::

    python scripts/generar_docx.py [--salida docs/entrega/Proyecto3_Documentacion.docx]

Convierte el subconjunto de Markdown que usa la documentación: títulos, párrafos con
**negrita**, *cursiva*, `código` y enlaces, listas, tablas, bloques de código, citas e
imágenes. Añade portada e índice (Word lo rellena al abrir el documento o con F9).
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"
SALIDA = DOCS / "entrega" / "Proyecto3_Documentacion.docx"
AZUL = RGBColor(0x1F, 0x4E, 0x79)

INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|!?\[[^\]]*\]\([^)]+\))")


def _anadir_texto(parrafo, texto: str) -> None:
    """Añade texto con formato en línea (negrita, cursiva, código, enlaces) a un párrafo."""
    for trozo in INLINE.split(texto):
        if not trozo:
            continue
        if trozo.startswith("**") and trozo.endswith("**"):
            parrafo.add_run(trozo[2:-2]).bold = True
        elif trozo.startswith("`") and trozo.endswith("`"):
            run = parrafo.add_run(trozo[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        elif trozo.startswith("[") or trozo.startswith("!["):
            enlace = re.match(r"!?\[([^\]]*)\]\(([^)]+)\)", trozo)
            run = parrafo.add_run(enlace.group(1))
            if enlace.group(2).startswith("http"):
                run.font.color.rgb = AZUL
                run.underline = True
        elif trozo.startswith("*") and trozo.endswith("*") and len(trozo) > 2:
            parrafo.add_run(trozo[1:-1]).italic = True
        else:
            parrafo.add_run(trozo)


def _celdas(linea: str) -> list[str]:
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def _tabla(documento, filas: list[str]) -> None:
    cabecera = _celdas(filas[0])
    cuerpo = [_celdas(f) for f in filas[2:]]
    tabla = documento.add_table(rows=1 + len(cuerpo), cols=len(cabecera))
    tabla.style = "Light Grid Accent 1"
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, fila in enumerate([cabecera, *cuerpo]):
        for j, texto in enumerate(fila[: len(cabecera)]):
            celda = tabla.cell(i, j)
            celda.text = ""
            parrafo = celda.paragraphs[0]
            _anadir_texto(parrafo, texto)
            for run in parrafo.runs:
                run.font.size = Pt(9)
                run.bold = run.bold or i == 0
    documento.add_paragraph()


def _codigo(documento, lineas: list[str]) -> None:
    parrafo = documento.add_paragraph()
    sombreado = OxmlElement("w:shd")
    sombreado.set(qn("w:val"), "clear")
    sombreado.set(qn("w:fill"), "F2F2F2")
    parrafo.paragraph_format._element.get_or_add_pPr().append(sombreado)
    run = parrafo.add_run("\n".join(lineas))
    run.font.name = "Consolas"
    run.font.size = Pt(8)


def convertir_markdown(documento, texto: str, carpeta: Path) -> None:
    """Añade al documento el contenido de un fichero Markdown."""
    lineas = texto.splitlines()
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if linea.startswith("```"):
            bloque = []
            i += 1
            while i < len(lineas) and not lineas[i].startswith("```"):
                bloque.append(lineas[i])
                i += 1
            _codigo(documento, bloque)
        elif linea.startswith("|"):
            filas = []
            while i < len(lineas) and lineas[i].startswith("|"):
                filas.append(lineas[i])
                i += 1
            _tabla(documento, filas)
            continue
        elif m := re.match(r"^(#{1,4})\s+(.*)", linea):
            documento.add_heading(m.group(2), level=len(m.group(1)))
        elif m := re.match(r"^!\[([^\]]*)\]\(([^)]+)\)", linea.strip()):
            imagen = (carpeta / m.group(2)).resolve()
            if imagen.exists():
                documento.add_picture(str(imagen), width=Cm(16))
                pie = documento.add_paragraph(m.group(1))
                pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pie.runs[0].italic = True
                pie.runs[0].font.size = Pt(9)
        elif m := re.match(r"^(\s*)[-*]\s+(.*)", linea):
            estilo = "List Bullet 2" if len(m.group(1)) >= 2 else "List Bullet"
            _anadir_texto(documento.add_paragraph(style=estilo), m.group(2))
        elif m := re.match(r"^\s*\d+\.\s+(.*)", linea):
            _anadir_texto(documento.add_paragraph(style="List Number"), m.group(1))
        elif linea.startswith(">"):
            parrafo = documento.add_paragraph()
            _anadir_texto(parrafo, linea.lstrip("> "))
            for run in parrafo.runs:
                run.italic = True
        elif linea.strip():
            _anadir_texto(documento.add_paragraph(), linea.strip())
        i += 1


def _indice(documento) -> None:
    """Inserta un campo de índice (TOC) que Word actualiza al abrir el documento."""
    run = documento.add_paragraph().add_run()
    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")
    instruccion = OxmlElement("w:instrText")
    instruccion.set(qn("xml:space"), "preserve")
    instruccion.text = 'TOC \\o "1-2" \\h \\z \\u'
    separador = OxmlElement("w:fldChar")
    separador.set(qn("w:fldCharType"), "separate")
    aviso = OxmlElement("w:t")
    aviso.text = "Pulsa F9 (o clic derecho → Actualizar campo) para generar el índice."
    fin = OxmlElement("w:fldChar")
    fin.set(qn("w:fldCharType"), "end")
    for elemento in (inicio, instruccion, separador, aviso, fin):
        run._r.append(elemento)
    actualizar = OxmlElement("w:updateFields")
    actualizar.set(qn("w:val"), "true")
    documento.settings.element.append(actualizar)


def _portada(documento) -> None:
    for _ in range(6):
        documento.add_paragraph()
    for texto, tamano, negrita in (
        ("Proyecto 3", 32, True),
        (
            "Sistema de Predicción de Viabilidad para la Instalación de un Centro de Procesamiento de Datos",
            18,
            False,
        ),
        ("", 12, False),
        ("Máster de Formación Profesional en Inteligencia Artificial y Big Data", 13, False),
        ("Stucom", 13, False),
        ("", 12, False),
        ("Mario Pérez · Arnau Higueras", 12, False),
        (date.today().strftime("%d/%m/%Y"), 11, False),
    ):
        parrafo = documento.add_paragraph()
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = parrafo.add_run(texto)
        run.font.size = Pt(tamano)
        run.bold = negrita
        run.font.color.rgb = AZUL
    documento.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def generar(salida: Path = SALIDA) -> Path:
    """Construye el documento Word con todos los ``docs/NN_*.md`` en orden."""
    documento = Document()
    estilo = documento.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(11)
    for seccion in documento.sections:
        seccion.left_margin = seccion.right_margin = Cm(2.2)

    _portada(documento)
    documento.add_heading("Índice", level=1)
    _indice(documento)

    for fichero in sorted(DOCS.glob("[0-9][0-9]_*.md")):
        documento.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        convertir_markdown(documento, fichero.read_text(encoding="utf-8"), fichero.parent)

    salida.parent.mkdir(parents=True, exist_ok=True)
    documento.save(salida)
    return salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera el documento de entrega en Word")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    print(f"Documento generado: {generar(parser.parse_args().salida)}")
