import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import (
    APP_DIR,
    DocumentPage,
    FRASE_PROVEEDOR,
    RESPUESTA_SALUD,
    compose_answer,
    record_aggregate,
)


class AsistentePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = [
            DocumentPage(
                number=2,
                text="Producto ficticio. Ingrediente de prueba: elemento beta.",
            )
        ]

    def test_responde_con_dato_ficticio_y_pagina(self) -> None:
        result = compose_answer(
            "¿Qué ingrediente contiene el producto ficticio?",
            self.pages,
            lambda _question, _pages: "Contiene el elemento beta.",
        )

        self.assertEqual(result["respuesta"], "Contiene el elemento beta.")
        self.assertEqual(
            result["fuentes"],
            [{"documento": "PDF autorizado", "pagina": 2}],
        )
        self.assertEqual(result["resultado"], "respondida")

    def test_dato_ausente_deriva_sin_consultar_al_modelo(self) -> None:
        responder_called = False

        def responder(_question: str, _pages: list[DocumentPage]) -> str:
            nonlocal responder_called
            responder_called = True
            return "Respuesta inventada."

        result = compose_answer(
            "¿Cuál es el grupo alimentario del producto?",
            [DocumentPage(number=1, text="La página no contiene esa información.")],
            responder,
        )

        self.assertEqual(result["respuesta"], FRASE_PROVEEDOR)
        self.assertEqual(result["resultado"], "derivada")
        self.assertFalse(responder_called)

    def test_acepta_variacion_singular_plural_al_buscar(self) -> None:
        result = compose_answer(
            "¿Qué ingredientes contiene el producto ficticio?",
            self.pages,
            lambda _question, _pages: "Contiene el elemento beta.",
        )

        self.assertEqual(result["resultado"], "respondida")
        self.assertEqual(result["fuentes"][0]["pagina"], 2)

    def test_no_afirma_beneficio_no_respaldado(self) -> None:
        responder_called = False

        def responder(_question: str, _pages: list[DocumentPage]) -> str:
            nonlocal responder_called
            responder_called = True
            return "Garantiza un resultado extraordinario."

        result = compose_answer(
            "¿Garantiza curar una condición?",
            self.pages,
            responder,
        )

        self.assertEqual(result["respuesta"], FRASE_PROVEEDOR)
        self.assertEqual(result["resultado"], "derivada")
        self.assertFalse(responder_called)

    def test_consulta_personal_de_salud_se_deriva(self) -> None:
        result = compose_answer(
            "¿Qué dosis debo tomar si tengo alergia?",
            self.pages,
            lambda _question, _pages: "No debería llamarse.",
        )

        self.assertEqual(result["respuesta"], RESPUESTA_SALUD)
        self.assertEqual(result["resultado"], "derivada")

    def test_base_local_solo_acumula_categoria_y_resultado(self) -> None:
        with tempfile.TemporaryDirectory(dir=APP_DIR) as temp_dir:
            database_path = Path(temp_dir) / "metricas.sqlite3"
            record_aggregate(database_path, "ingredientes", "respondida")
            record_aggregate(database_path, "ingredientes", "respondida")

            with closing(sqlite3.connect(database_path)) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(consulta_resumen)"
                    )
                }
                quantity = connection.execute(
                    """
                    SELECT cantidad
                    FROM consulta_resumen
                    WHERE categoria = ? AND resultado = ?
                    """,
                    ("ingredientes", "respondida"),
                ).fetchone()[0]

        self.assertEqual(quantity, 2)
        self.assertEqual(columns, {"categoria", "resultado", "cantidad"})


if __name__ == "__main__":
    unittest.main()
