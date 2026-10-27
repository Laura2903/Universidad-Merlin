import tempfile
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import crear_app


def new_id() -> str:
    return str(uuid.uuid4())


class FarmaVisitaApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "tests.sqlite3"
        self.app = crear_app(
            {
                "TESTING": True,
                "DATABASE": str(self.db_path),
            }
        )
        self.client = self.app.test_client()
        self.farmacia = {
            "id": new_id(),
            "nombre": "Farmacia de prueba",
            "direccion": "Dirección ficticia",
        }
        self.producto = {
            "id": new_id(),
            "nombre": "Producto de prueba",
            "sku": "PRUEBA-001",
            "presentacion": "Unidad de prueba",
            "precio_unitario": 12.35,
            "existencias": 5,
            "stock_minimo": 5,
            "activo": True,
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def crear_datos_base(self) -> None:
        self.assertEqual(
            self.client.post("/api/farmacias", json=self.farmacia).status_code,
            201,
        )
        self.assertEqual(
            self.client.post("/api/productos", json=self.producto).status_code,
            201,
        )

    def crear_movimiento(self, movement_id: str, tipo: str, cantidad: int):
        return self.client.post(
            "/api/inventario/movimientos",
            json={
                "id": movement_id,
                "producto_id": self.producto["id"],
                "tipo": tipo,
                "cantidad": cantidad,
                "fecha": "2026-10-26",
                "motivo": "Prueba automatizada",
            },
        )

    def test_health_and_app_shell(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "base_datos": "conectada"})
        self.assertIn(b"FarmaVisita", self.client.get("/").data)
        worker_response = self.client.get("/service-worker.js")
        self.assertEqual(worker_response.status_code, 200)
        worker_response.close()

    def test_create_list_and_update_pharmacy(self) -> None:
        created = self.client.post("/api/farmacias", json=self.farmacia)
        self.assertEqual(created.status_code, 201)
        listed = self.client.get("/api/farmacias?q=Farmacia")
        self.assertEqual(listed.get_json()[0]["id"], self.farmacia["id"])
        updated = self.client.put(
            f"/api/farmacias/{self.farmacia['id']}",
            json={"direccion": "Dirección actualizada"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            self.client.get("/api/farmacias").get_json()[0]["direccion"],
            "Dirección actualizada",
        )

    def test_create_visit(self) -> None:
        self.crear_datos_base()
        response = self.client.post(
            "/api/visitas",
            json={
                "id": new_id(),
                "farmacia_id": self.farmacia["id"],
                "fecha_hora": "2026-10-26T09:30:00-06:00",
                "resultado": "realizada",
                "comentarios": "Visita de prueba",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.client.get("/api/visitas").get_json()), 1)

    def test_update_product_preserves_physical_stock(self) -> None:
        self.client.post("/api/productos", json=self.producto)
        response = self.client.put(
            f"/api/productos/{self.producto['id']}",
            json={"precio_unitario": 15.75, "stock_minimo": 3},
        )
        self.assertEqual(response.status_code, 200)
        product = response.get_json()["producto"]
        self.assertEqual(product["precio_unitario"], 15.75)
        self.assertEqual(product["stock_minimo"], 3)
        self.assertEqual(product["existencias"], 5)

    def test_order_total_uses_backend_prices_and_does_not_change_stock(self) -> None:
        self.crear_datos_base()
        second = dict(self.producto)
        second.update(
            id=new_id(),
            nombre="Otro producto de prueba",
            sku="PRUEBA-002",
            precio_unitario=5.50,
        )
        self.assertEqual(self.client.post("/api/productos", json=second).status_code, 201)
        response = self.client.post(
            "/api/pedidos",
            json={
                "id": new_id(),
                "farmacia_id": self.farmacia["id"],
                "fecha": "2026-10-26",
                "estado": "registrado",
                "total": 0.01,
                "productos": [
                    {"producto_id": self.producto["id"], "cantidad": 2, "precio_unitario": 0},
                    {"producto_id": second["id"], "cantidad": 3, "precio_unitario": 0},
                ],
            },
        )
        self.assertEqual(response.status_code, 201)
        order_id = response.get_json()["pedido"]["id"]
        listed = self.client.get("/api/pedidos").get_json()
        order = next(item for item in listed if item["id"] == order_id)
        self.assertEqual(order["total"], 41.2)
        inventory = self.client.get("/api/inventario").get_json()
        self.assertEqual(
            next(item for item in inventory if item["id"] == self.producto["id"])[
                "existencias"
            ],
            5,
        )

    def test_inventory_entry_exit_and_invalid_quantities(self) -> None:
        self.crear_datos_base()
        entry = self.crear_movimiento(new_id(), "entrada", 4)
        self.assertEqual(entry.status_code, 201)
        exit_response = self.crear_movimiento(new_id(), "salida", 3)
        self.assertEqual(exit_response.status_code, 201)
        stock = self.client.get("/api/inventario").get_json()[0]["existencias"]
        self.assertEqual(stock, 6)

        negative = self.client.post(
            "/api/inventario/movimientos",
            json={
                "id": new_id(),
                "producto_id": self.producto["id"],
                "tipo": "entrada",
                "cantidad": -1,
                "motivo": "Inválido",
            },
        )
        self.assertEqual(negative.status_code, 400)
        oversell = self.crear_movimiento(new_id(), "salida", 100)
        self.assertEqual(oversell.status_code, 409)

    def test_duplicate_inventory_movement_does_not_apply_stock_twice(self) -> None:
        self.crear_datos_base()
        movement_id = new_id()
        first = self.crear_movimiento(movement_id, "entrada", 4)
        second = self.crear_movimiento(movement_id, "entrada", 4)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["duplicado"])
        stock = self.client.get("/api/inventario").get_json()[0]["existencias"]
        self.assertEqual(stock, 9)

    def test_invalid_order_quantity_is_rejected(self) -> None:
        self.crear_datos_base()
        response = self.client.post(
            "/api/pedidos",
            json={
                "id": new_id(),
                "farmacia_id": self.farmacia["id"],
                "productos": [
                    {"producto_id": self.producto["id"], "cantidad": 0}
                ],
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_sync_is_idempotent_and_reports_conflict_without_duplicate(self) -> None:
        record = {
            "tipo": "farmacias",
            "id": self.farmacia["id"],
            "datos": self.farmacia,
        }
        response = self.client.post("/api/sync", json={"registros": [record, record]})
        results = response.get_json()["resultados"]
        self.assertEqual([result["ok"] for result in results], [True, True])
        self.assertFalse(results[0]["duplicado"])
        self.assertTrue(results[1]["duplicado"])
        self.assertEqual(len(self.client.get("/api/farmacias").get_json()), 1)

        conflicting = {
            **record,
            "datos": {**self.farmacia, "nombre": "Otro nombre"},
        }
        conflict = self.client.post(
            "/api/sync", json={"registros": [conflicting]}
        ).get_json()["resultados"][0]
        self.assertFalse(conflict["ok"])
        self.assertIn("datos diferentes", conflict["error"])
        self.assertEqual(len(self.client.get("/api/farmacias").get_json()), 1)

    def test_sync_saves_related_records_in_dependency_order(self) -> None:
        pharmacy_id = new_id()
        product_id = new_id()
        visit_id = new_id()
        pharmacy = {"id": pharmacy_id, "nombre": "Farmacia local"}
        product = {
            "id": product_id,
            "nombre": "Producto local",
            "sku": "SYNC-001",
            "precio_unitario": 20,
            "existencias": 2,
        }
        visit = {
            "id": visit_id,
            "farmacia_id": pharmacy_id,
            "fecha_hora": "2026-10-26T10:00:00",
            "resultado": "seguimiento_pendiente",
        }
        records = [
            {"tipo": "visitas", "id": visit_id, "datos": visit},
            {"tipo": "productos", "id": product_id, "datos": product},
            {"tipo": "farmacias", "id": pharmacy_id, "datos": pharmacy},
        ]
        result = self.client.post(
            "/api/sync", json={"registros": records}
        ).get_json()["resultados"]
        self.assertTrue(all(item["ok"] for item in result))
        self.assertEqual(len(self.client.get("/api/visitas").get_json()), 1)

    def test_records_persist_after_app_restarts(self) -> None:
        self.client.post("/api/farmacias", json=self.farmacia)
        new_app = crear_app(
            {"TESTING": True, "DATABASE": str(self.db_path)}
        )
        response = new_app.test_client().get("/api/farmacias")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["id"], self.farmacia["id"])

    def test_reports_distinguish_ordered_amount_and_low_stock(self) -> None:
        self.crear_datos_base()
        self.client.post(
            "/api/pedidos",
            json={
                "id": new_id(),
                "farmacia_id": self.farmacia["id"],
                "fecha": "2026-10-26",
                "productos": [
                    {"producto_id": self.producto["id"], "cantidad": 2}
                ],
            },
        )
        report = self.client.get("/api/reportes?desde=2026-10-01").get_json()
        self.assertEqual(report["pedidos"], 1)
        self.assertEqual(report["importe_pedidos_registrados"], 24.7)
        self.assertEqual(report["existencias_bajas"][0]["id"], self.producto["id"])

    def test_frontend_offline_storage_and_sync_assets_are_present(self) -> None:
        static_dir = Path(__file__).resolve().parents[1] / "static"
        db_script = (static_dir / "js" / "db.js").read_text(encoding="utf-8")
        sync_script = (static_dir / "js" / "sync.js").read_text(encoding="utf-8")
        worker = (static_dir / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("indexedDB.open", db_script)
        self.assertIn("/api/sync", sync_script)
        self.assertIn("caches.open", worker)
        self.assertIn("Sincronizar ahora", (static_dir.parent / "templates" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
