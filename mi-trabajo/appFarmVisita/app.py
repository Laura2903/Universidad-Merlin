import os
import sqlite3
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

import database


RESULTADOS_VISITA = {
    "realizada",
    "encargado_ausente",
    "seguimiento_pendiente",
    "no_concretada",
}
ESTADOS_PEDIDO = {"borrador", "registrado", "enviado", "cancelado"}
TIPOS_MOVIMIENTO = {"entrada", "salida", "ajuste"}
TIPOS_SYNC = {"farmacias", "productos", "visitas", "pedidos", "movimientos"}
CENTAVOS = Decimal("0.01")


class ErrorValidacion(Exception):
    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def crear_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(Path(__file__).resolve().parent / "farmavisita.sqlite3"),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    database.init_app(app)

    def body_json() -> dict[str, Any]:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ErrorValidacion("Envía los datos en formato JSON.")
        return data

    def texto(
        data: dict[str, Any],
        campo: str,
        *,
        requerido: bool = False,
        maximo: int = 500,
        defecto: str = "",
    ) -> str:
        valor = data.get(campo, defecto)
        if not isinstance(valor, str):
            raise ErrorValidacion(f"El campo {campo} debe ser texto.")
        valor = valor.strip()
        if requerido and not valor:
            raise ErrorValidacion(f"El campo {campo} es obligatorio.")
        if len(valor) > maximo:
            raise ErrorValidacion(f"El campo {campo} supera {maximo} caracteres.")
        return valor

    def identificador(data: dict[str, Any]) -> str:
        valor = texto(data, "id", requerido=True, maximo=36)
        try:
            return str(uuid.UUID(valor))
        except ValueError as error:
            raise ErrorValidacion("El identificador debe ser un UUID válido.") from error

    def referencia_uuid(valor: str, campo: str) -> str:
        try:
            return str(uuid.UUID(valor))
        except ValueError as error:
            raise ErrorValidacion(f"El identificador {campo} no es un UUID válido.") from error

    def entero(
        data: dict[str, Any],
        campo: str,
        *,
        minimo: int = 0,
        defecto: int | None = None,
    ) -> int:
        valor = data.get(campo, defecto)
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
            raise ErrorValidacion(
                f"El campo {campo} debe ser un número entero de al menos {minimo}."
            )
        return valor

    def dinero(data: dict[str, Any], campo: str, defecto: Any = None) -> Decimal:
        valor = data.get(campo, defecto)
        if isinstance(valor, bool) or valor is None:
            raise ErrorValidacion(f"El campo {campo} debe ser un número válido.")
        try:
            cantidad = Decimal(str(valor))
        except (InvalidOperation, ValueError) as error:
            raise ErrorValidacion(f"El campo {campo} debe ser un número válido.") from error
        if not cantidad.is_finite() or cantidad < 0:
            raise ErrorValidacion(f"El campo {campo} no puede ser negativo.")
        return cantidad.quantize(CENTAVOS, rounding=ROUND_HALF_UP)

    def fecha_valida(valor: str, campo: str) -> str:
        if not valor:
            return ahora()
        try:
            datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            try:
                date.fromisoformat(valor)
            except ValueError as error:
                raise ErrorValidacion(
                    f"El campo {campo} debe tener formato ISO de fecha."
                ) from error
        return valor

    def insertar_idempotente(
        db: sqlite3.Connection,
        tabla: str,
        valores: dict[str, Any],
        *,
        campos_comparacion: tuple[str, ...],
    ) -> bool:
        actual = db.execute(
            f"SELECT * FROM {tabla} WHERE id = ?", (valores["id"],)
        ).fetchone()
        if actual:
            if all(actual[campo] == valores[campo] for campo in campos_comparacion):
                return False
            raise ErrorValidacion(
                "El identificador ya existe con datos diferentes.",
                codigo=409,
            )
        columnas = ", ".join(valores)
        marcadores = ", ".join("?" for _ in valores)
        db.execute(
            f"INSERT INTO {tabla} ({columnas}) VALUES ({marcadores})",
            tuple(valores.values()),
        )
        return True

    def crear_farmacia(
        db: sqlite3.Connection, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        valores = {
            "id": identificador(data),
            "nombre": texto(data, "nombre", requerido=True, maximo=120),
            "direccion": texto(data, "direccion", maximo=250),
            "encargado": texto(data, "encargado", maximo=120),
            "telefono": texto(data, "telefono", maximo=40),
            "observaciones": texto(data, "observaciones", maximo=1000),
            "fecha_creacion": fecha_valida(
                texto(data, "fecha_creacion", maximo=40), "fecha_creacion"
            ),
        }
        creado = insertar_idempotente(
            db,
            "farmacias",
            valores,
            campos_comparacion=(
                "nombre", "direccion", "encargado", "telefono", "observaciones"
            ),
        )
        return valores, creado

    def crear_producto(
        db: sqlite3.Connection, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        activo = data.get("activo", True)
        if not isinstance(activo, bool):
            raise ErrorValidacion("El campo activo debe ser verdadero o falso.")
        valores = {
            "id": identificador(data),
            "nombre": texto(data, "nombre", requerido=True, maximo=120),
            "sku": texto(data, "sku", requerido=True, maximo=60),
            "presentacion": texto(data, "presentacion", maximo=120),
            "precio_unitario": float(dinero(data, "precio_unitario", 0)),
            "existencias": entero(data, "existencias", defecto=0),
            "stock_minimo": entero(data, "stock_minimo", defecto=0),
            "activo": int(activo),
            "fecha_creacion": fecha_valida(
                texto(data, "fecha_creacion", maximo=40), "fecha_creacion"
            ),
        }
        creado = insertar_idempotente(
            db,
            "productos",
            valores,
            campos_comparacion=(
                "nombre", "sku", "presentacion", "precio_unitario",
                "existencias", "stock_minimo", "activo"
            ),
        )
        return valores, creado

    def crear_visita(
        db: sqlite3.Connection, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        resultado = texto(data, "resultado", requerido=True, maximo=40)
        if resultado not in RESULTADOS_VISITA:
            raise ErrorValidacion("El resultado de visita no es válido.")
        valores = {
            "id": identificador(data),
            "farmacia_id": referencia_uuid(
                texto(data, "farmacia_id", requerido=True, maximo=36),
                "farmacia_id",
            ),
            "fecha_hora": fecha_valida(
                texto(data, "fecha_hora", maximo=40), "fecha_hora"
            ),
            "resultado": resultado,
            "comentarios": texto(data, "comentarios", maximo=1000),
            "proxima_fecha": texto(data, "proxima_fecha", maximo=40),
            "fecha_creacion": fecha_valida(
                texto(data, "fecha_creacion", maximo=40), "fecha_creacion"
            ),
        }
        creado = insertar_idempotente(
            db,
            "visitas",
            valores,
            campos_comparacion=(
                "farmacia_id", "fecha_hora", "resultado", "comentarios",
                "proxima_fecha"
            ),
        )
        return valores, creado

    def crear_pedido(
        db: sqlite3.Connection, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        id_pedido = identificador(data)
        farmacia_id = referencia_uuid(
            texto(data, "farmacia_id", requerido=True, maximo=36),
            "farmacia_id",
        )
        fecha = fecha_valida(texto(data, "fecha", maximo=40), "fecha")
        estado = texto(data, "estado", maximo=30, defecto="registrado")
        if estado not in ESTADOS_PEDIDO:
            raise ErrorValidacion("El estado del pedido no es válido.")
        lineas = data.get("productos")
        if not isinstance(lineas, list) or not lineas:
            raise ErrorValidacion("Agrega al menos un producto al pedido.")
        if len(lineas) > 100:
            raise ErrorValidacion("Un pedido admite hasta 100 productos.")

        normalizadas: list[dict[str, Any]] = []
        productos_vistos: set[str] = set()
        total = Decimal("0")
        for linea in lineas:
            if not isinstance(linea, dict):
                raise ErrorValidacion("Cada producto del pedido debe ser un objeto.")
            producto_id = texto(linea, "producto_id", requerido=True, maximo=36)
            try:
                producto_id = str(uuid.UUID(producto_id))
            except ValueError as error:
                raise ErrorValidacion("El identificador del producto no es válido.") from error
            if producto_id in productos_vistos:
                raise ErrorValidacion("No repitas un producto dentro del pedido.")
            productos_vistos.add(producto_id)
            cantidad = entero(linea, "cantidad", minimo=1)
            producto = db.execute(
                "SELECT id, precio_unitario, activo FROM productos WHERE id = ?",
                (producto_id,),
            ).fetchone()
            if not producto or not producto["activo"]:
                raise ErrorValidacion(
                    "Un producto del pedido no existe o está inactivo.",
                    codigo=409,
                )
            precio = Decimal(str(producto["precio_unitario"])).quantize(CENTAVOS)
            subtotal = precio * cantidad
            total += subtotal
            normalizadas.append(
                {
                    "id": str(uuid.uuid5(uuid.UUID(id_pedido), producto_id)),
                    "producto_id": producto_id,
                    "cantidad": cantidad,
                    "precio_unitario": float(precio),
                }
            )
        total = total.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
        valores = {
            "id": id_pedido,
            "farmacia_id": farmacia_id,
            "fecha": fecha,
            "estado": estado,
            "observaciones": texto(data, "observaciones", maximo=1000),
            "total": float(total),
            "fecha_creacion": fecha_valida(
                texto(data, "fecha_creacion", maximo=40), "fecha_creacion"
            ),
        }
        existente = db.execute(
            "SELECT * FROM pedidos WHERE id = ?", (id_pedido,)
        ).fetchone()
        if existente:
            anteriores = db.execute(
                """
                SELECT producto_id, cantidad FROM detalle_pedido
                WHERE pedido_id = ? ORDER BY producto_id
                """,
                (id_pedido,),
            ).fetchall()
            recibidos = sorted(
                (linea["producto_id"], linea["cantidad"]) for linea in normalizadas
            )
            iguales = (
                existente["farmacia_id"] == valores["farmacia_id"]
                and existente["fecha"] == valores["fecha"]
                and existente["estado"] == valores["estado"]
                and existente["observaciones"] == valores["observaciones"]
                and [(fila["producto_id"], fila["cantidad"]) for fila in anteriores]
                == recibidos
            )
            if iguales:
                return valores, False
            raise ErrorValidacion(
                "El identificador del pedido ya existe con datos diferentes.",
                codigo=409,
            )

        db.execute(
            """
            INSERT INTO pedidos
                (id, farmacia_id, fecha, estado, observaciones, total, fecha_creacion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(valores.values()),
        )
        db.executemany(
            """
            INSERT INTO detalle_pedido
                (id, pedido_id, producto_id, cantidad, precio_unitario)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    linea["id"],
                    id_pedido,
                    linea["producto_id"],
                    linea["cantidad"],
                    linea["precio_unitario"],
                )
                for linea in normalizadas
            ],
        )
        return valores, True

    def crear_movimiento(
        db: sqlite3.Connection, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        id_movimiento = identificador(data)
        producto_id = texto(data, "producto_id", requerido=True, maximo=36)
        try:
            producto_id = str(uuid.UUID(producto_id))
        except ValueError as error:
            raise ErrorValidacion("El identificador del producto no es válido.") from error
        tipo = texto(data, "tipo", requerido=True, maximo=20)
        if tipo not in TIPOS_MOVIMIENTO:
            raise ErrorValidacion("El tipo de movimiento no es válido.")
        cantidad = entero(
            data, "cantidad", minimo=0 if tipo == "ajuste" else 1
        )
        motivo = texto(data, "motivo", requerido=True, maximo=250)
        fecha = fecha_valida(texto(data, "fecha", maximo=40), "fecha")
        existente = db.execute(
            "SELECT * FROM movimientos_inventario WHERE id = ?",
            (id_movimiento,),
        ).fetchone()
        if existente:
            if (
                existente["producto_id"] == producto_id
                and existente["tipo"] == tipo
                and existente["cantidad"] == cantidad
                and existente["motivo"] == motivo
                and existente["fecha"] == fecha
            ):
                return dict(existente), False
            raise ErrorValidacion(
                "El identificador del movimiento ya existe con datos diferentes.",
                codigo=409,
            )
        producto = db.execute(
            "SELECT existencias FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if not producto:
            raise ErrorValidacion("El producto indicado no existe.", codigo=404)
        anterior = producto["existencias"]
        if tipo == "entrada":
            nuevo_stock = anterior + cantidad
        elif tipo == "salida":
            nuevo_stock = anterior - cantidad
        else:
            nuevo_stock = cantidad
        if nuevo_stock < 0:
            raise ErrorValidacion(
                "La salida supera las existencias disponibles.", codigo=409
            )
        valores = {
            "id": id_movimiento,
            "producto_id": producto_id,
            "tipo": tipo,
            "cantidad": cantidad,
            "motivo": motivo,
            "fecha": fecha,
            "existencia_resultante": nuevo_stock,
            "fecha_creacion": fecha_valida(
                texto(data, "fecha_creacion", maximo=40), "fecha_creacion"
            ),
        }
        db.execute(
            "UPDATE productos SET existencias = ? WHERE id = ?",
            (nuevo_stock, producto_id),
        )
        columnas = ", ".join(valores)
        marcadores = ", ".join("?" for _ in valores)
        db.execute(
            f"INSERT INTO movimientos_inventario ({columnas}) VALUES ({marcadores})",
            tuple(valores.values()),
        )
        return valores, True

    def procesar_registro(
        db: sqlite3.Connection, tipo: str, data: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        funciones = {
            "farmacias": crear_farmacia,
            "productos": crear_producto,
            "visitas": crear_visita,
            "pedidos": crear_pedido,
            "movimientos": crear_movimiento,
        }
        if tipo not in funciones:
            raise ErrorValidacion("El tipo de registro no está permitido.")
        return funciones[tipo](db, data)

    def manejar_error(error: ErrorValidacion):
        return jsonify({"error": str(error)}), error.codigo

    @app.errorhandler(ErrorValidacion)
    def error_validacion(error: ErrorValidacion):
        return manejar_error(error)

    @app.get("/")
    def inicio():
        return render_template("index.html")

    @app.get("/service-worker.js")
    def service_worker():
        respuesta = send_from_directory(app.static_folder, "service-worker.js")
        respuesta.headers["Service-Worker-Allowed"] = "/"
        return respuesta

    @app.get("/api/health")
    def health():
        db = database.get_db()
        db.execute("SELECT 1")
        return jsonify({"ok": True, "base_datos": "conectada"})

    @app.get("/api/farmacias")
    def listar_farmacias():
        db = database.get_db()
        busqueda = request.args.get("q", "").strip()
        if busqueda:
            filas = db.execute(
                """
                SELECT * FROM farmacias WHERE nombre LIKE ?
                ORDER BY nombre COLLATE NOCASE
                """,
                (f"%{busqueda}%",),
            ).fetchall()
        else:
            filas = db.execute(
                "SELECT * FROM farmacias ORDER BY nombre COLLATE NOCASE"
            ).fetchall()
        return jsonify([dict(fila) for fila in filas])

    @app.post("/api/farmacias")
    def alta_farmacia():
        data = body_json()
        db = database.get_db()
        try:
            valores, creado = procesar_registro(db, "farmacias", data)
            db.commit()
        except ErrorValidacion:
            db.rollback()
            raise
        except sqlite3.IntegrityError as error:
            db.rollback()
            raise ErrorValidacion("No se pudo guardar la farmacia.", 409) from error
        return jsonify({"farmacia": valores, "duplicado": not creado}), (
            201 if creado else 200
        )

    @app.put("/api/farmacias/<farmacia_id>")
    def editar_farmacia(farmacia_id: str):
        data = body_json()
        db = database.get_db()
        existente = db.execute(
            "SELECT * FROM farmacias WHERE id = ?", (farmacia_id,)
        ).fetchone()
        if not existente:
            raise ErrorValidacion("No se encontró la farmacia.", 404)
        actualizado = dict(existente)
        for campo, maximo in (
            ("nombre", 120), ("direccion", 250), ("encargado", 120),
            ("telefono", 40), ("observaciones", 1000)
        ):
            if campo in data:
                actualizado[campo] = texto(
                    data, campo, requerido=(campo == "nombre"), maximo=maximo
                )
        db.execute(
            """
            UPDATE farmacias
            SET nombre = ?, direccion = ?, encargado = ?, telefono = ?,
                observaciones = ?
            WHERE id = ?
            """,
            (
                actualizado["nombre"], actualizado["direccion"],
                actualizado["encargado"], actualizado["telefono"],
                actualizado["observaciones"], farmacia_id,
            ),
        )
        db.commit()
        return jsonify({"farmacia": actualizado})

    @app.get("/api/visitas")
    def listar_visitas():
        farmacia_id = request.args.get("farmacia_id")
        db = database.get_db()
        if farmacia_id:
            filas = db.execute(
                """
                SELECT v.*, f.nombre AS farmacia_nombre
                FROM visitas v JOIN farmacias f ON f.id = v.farmacia_id
                WHERE v.farmacia_id = ? ORDER BY v.fecha_hora DESC
                """,
                (farmacia_id,),
            ).fetchall()
        else:
            filas = db.execute(
                """
                SELECT v.*, f.nombre AS farmacia_nombre
                FROM visitas v JOIN farmacias f ON f.id = v.farmacia_id
                ORDER BY v.fecha_hora DESC LIMIT 200
                """
            ).fetchall()
        return jsonify([dict(fila) for fila in filas])

    @app.post("/api/visitas")
    def alta_visita():
        return crear_respuesta("visitas", body_json())

    @app.get("/api/productos")
    def listar_productos():
        filas = database.get_db().execute(
            "SELECT * FROM productos ORDER BY activo DESC, nombre COLLATE NOCASE"
        ).fetchall()
        return jsonify([dict(fila) for fila in filas])

    @app.post("/api/productos")
    def alta_producto():
        return crear_respuesta("productos", body_json())

    @app.put("/api/productos/<producto_id>")
    def editar_producto(producto_id: str):
        data = body_json()
        db = database.get_db()
        existente = db.execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        if not existente:
            raise ErrorValidacion("No se encontró el producto.", 404)
        actualizado = dict(existente)
        if "nombre" in data:
            actualizado["nombre"] = texto(data, "nombre", requerido=True, maximo=120)
        if "sku" in data:
            actualizado["sku"] = texto(data, "sku", requerido=True, maximo=60)
        if "presentacion" in data:
            actualizado["presentacion"] = texto(data, "presentacion", maximo=120)
        if "precio_unitario" in data:
            actualizado["precio_unitario"] = float(
                dinero(data, "precio_unitario")
            )
        if "stock_minimo" in data:
            actualizado["stock_minimo"] = entero(data, "stock_minimo")
        if "activo" in data:
            if not isinstance(data["activo"], bool):
                raise ErrorValidacion("El campo activo debe ser verdadero o falso.")
            actualizado["activo"] = int(data["activo"])
        try:
            db.execute(
                """
                UPDATE productos SET nombre = ?, sku = ?, presentacion = ?,
                    precio_unitario = ?, stock_minimo = ?, activo = ?
                WHERE id = ?
                """,
                (
                    actualizado["nombre"], actualizado["sku"],
                    actualizado["presentacion"], actualizado["precio_unitario"],
                    actualizado["stock_minimo"], actualizado["activo"],
                    producto_id,
                ),
            )
            db.commit()
        except sqlite3.IntegrityError as error:
            db.rollback()
            raise ErrorValidacion(
                "Ese SKU ya está asignado a otro producto.",
                409,
            ) from error
        producto = db.execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        return jsonify({"producto": dict(producto)})

    @app.get("/api/pedidos")
    def listar_pedidos():
        db = database.get_db()
        filas = db.execute(
            """
            SELECT p.*, f.nombre AS farmacia_nombre
            FROM pedidos p JOIN farmacias f ON f.id = p.farmacia_id
            ORDER BY p.fecha DESC LIMIT 200
            """
        ).fetchall()
        pedidos = []
        for fila in filas:
            pedido = dict(fila)
            pedido["productos"] = [
                dict(linea)
                for linea in db.execute(
                    """
                    SELECT d.producto_id, d.cantidad, d.precio_unitario,
                           pr.nombre AS producto_nombre
                    FROM detalle_pedido d
                    JOIN productos pr ON pr.id = d.producto_id
                    WHERE d.pedido_id = ?
                    """,
                    (pedido["id"],),
                ).fetchall()
            ]
            pedidos.append(pedido)
        return jsonify(pedidos)

    @app.post("/api/pedidos")
    def alta_pedido():
        return crear_respuesta("pedidos", body_json())

    @app.get("/api/inventario")
    def inventario():
        filas = database.get_db().execute(
            "SELECT * FROM productos ORDER BY nombre COLLATE NOCASE"
        ).fetchall()
        return jsonify([dict(fila) for fila in filas])

    @app.get("/api/inventario/movimientos")
    def listar_movimientos():
        filas = database.get_db().execute(
            """
            SELECT m.*, p.nombre AS producto_nombre
            FROM movimientos_inventario m
            JOIN productos p ON p.id = m.producto_id
            ORDER BY m.fecha DESC LIMIT 200
            """
        ).fetchall()
        return jsonify([dict(fila) for fila in filas])

    @app.post("/api/inventario/movimientos")
    def alta_movimiento():
        return crear_respuesta("movimientos", body_json())

    @app.get("/api/reportes")
    def reportes():
        db = database.get_db()
        desde = request.args.get("desde", "")
        hasta = request.args.get("hasta", "")
        for nombre, valor in (("desde", desde), ("hasta", hasta)):
            if valor:
                try:
                    date.fromisoformat(valor)
                except ValueError as error:
                    raise ErrorValidacion(
                        f"El filtro {nombre} debe ser una fecha ISO."
                    ) from error
        condiciones_visitas = []
        parametros_visitas: list[Any] = []
        condiciones_pedidos = ["estado != 'cancelado'"]
        parametros_pedidos: list[Any] = []
        if desde:
            condiciones_visitas.append("date(fecha_hora) >= date(?)")
            parametros_visitas.append(desde)
            condiciones_pedidos.append("date(fecha) >= date(?)")
            parametros_pedidos.append(desde)
        if hasta:
            condiciones_visitas.append("date(fecha_hora) <= date(?)")
            parametros_visitas.append(hasta)
            condiciones_pedidos.append("date(fecha) <= date(?)")
            parametros_pedidos.append(hasta)
        where_visitas = (
            " WHERE " + " AND ".join(condiciones_visitas)
            if condiciones_visitas else ""
        )
        where_pedidos = " WHERE " + " AND ".join(condiciones_pedidos)
        visitas = db.execute(
            f"SELECT COUNT(*) AS cantidad FROM visitas{where_visitas}",
            parametros_visitas,
        ).fetchone()["cantidad"]
        pedidos = db.execute(
            f"""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(total), 0) AS importe
            FROM pedidos{where_pedidos}
            """,
            parametros_pedidos,
        ).fetchone()
        productos = db.execute(
            """
            SELECT p.id, p.nombre,
                   COALESCE(SUM(CASE WHEN o.id IS NOT NULL THEN d.cantidad ELSE 0 END), 0)
                       AS unidades
            FROM productos p LEFT JOIN detalle_pedido d ON d.producto_id = p.id
            LEFT JOIN pedidos o ON o.id = d.pedido_id AND o.estado != 'cancelado'
                AND (? = '' OR date(o.fecha) >= date(?))
                AND (? = '' OR date(o.fecha) <= date(?))
            GROUP BY p.id ORDER BY unidades DESC, p.nombre COLLATE NOCASE LIMIT 5
            """,
            (desde, desde, hasta, hasta),
        ).fetchall()
        stock_bajo = db.execute(
            """
            SELECT id, nombre, existencias, stock_minimo FROM productos
            WHERE activo = 1 AND existencias <= stock_minimo
            ORDER BY existencias, nombre COLLATE NOCASE
            """
        ).fetchall()
        return jsonify(
            {
                "visitas": visitas,
                "pedidos": pedidos["cantidad"],
                "importe_pedidos_registrados": round(pedidos["importe"], 2),
                "productos_mas_solicitados": [dict(fila) for fila in productos],
                "existencias_bajas": [dict(fila) for fila in stock_bajo],
            }
        )

    @app.post("/api/sync")
    def sincronizar():
        data = body_json()
        registros = data.get("registros")
        if not isinstance(registros, list):
            raise ErrorValidacion("El campo registros debe ser una lista.")
        if len(registros) > 100:
            raise ErrorValidacion("Sincroniza hasta 100 registros por solicitud.")
        prioridades = {
            "farmacias": 0, "productos": 1, "visitas": 2,
            "pedidos": 3, "movimientos": 4
        }
        ordenados = sorted(
            registros,
            key=lambda item: prioridades.get(item.get("tipo"), 99)
            if isinstance(item, dict) and isinstance(item.get("tipo"), str)
            else 99,
        )
        resultados = []
        db = database.get_db()
        for registro in ordenados:
            if not isinstance(registro, dict):
                resultados.append(
                    {"ok": False, "error": "El registro debe ser un objeto."}
                )
                continue
            tipo = registro.get("tipo")
            record_id = registro.get("id")
            contenido = registro.get("datos")
            if (
                not isinstance(tipo, str)
                or tipo not in TIPOS_SYNC
                or not isinstance(contenido, dict)
            ):
                resultados.append(
                    {
                        "tipo": tipo,
                        "id": record_id,
                        "ok": False,
                        "error": "Tipo o datos del registro no válidos.",
                    }
                )
                continue
            if contenido.get("id") != record_id:
                resultados.append(
                    {
                        "tipo": tipo,
                        "id": record_id,
                        "ok": False,
                        "error": "El identificador del sobre no coincide con los datos.",
                        "codigo": 400,
                    }
                )
                continue
            try:
                db.execute("SAVEPOINT sync_record")
                valores, creado = procesar_registro(db, tipo, contenido)
                db.execute("RELEASE SAVEPOINT sync_record")
                db.commit()
                resultados.append(
                    {
                        "tipo": tipo,
                        "id": valores["id"],
                        "ok": True,
                        "duplicado": not creado,
                    }
                )
            except ErrorValidacion as error:
                db.execute("ROLLBACK TO SAVEPOINT sync_record")
                db.execute("RELEASE SAVEPOINT sync_record")
                db.commit()
                resultados.append(
                    {
                        "tipo": tipo,
                        "id": record_id,
                        "ok": False,
                        "error": str(error),
                        "codigo": error.codigo,
                    }
                )
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK TO SAVEPOINT sync_record")
                db.execute("RELEASE SAVEPOINT sync_record")
                db.commit()
                resultados.append(
                    {
                        "tipo": tipo,
                        "id": record_id,
                        "ok": False,
                        "error": (
                            "No se pudo sincronizar: revisa las relaciones y "
                            "que el SKU no esté duplicado."
                        ),
                        "codigo": 409,
                    }
                )
        return jsonify({"resultados": resultados})

    def crear_respuesta(tipo: str, data: dict[str, Any]):
        db = database.get_db()
        try:
            valores, creado = procesar_registro(db, tipo, data)
            db.commit()
        except ErrorValidacion:
            db.rollback()
            raise
        except sqlite3.IntegrityError as error:
            db.rollback()
            raise ErrorValidacion(
                "No se pudo guardar: revisa que los registros relacionados existan "
                "y que los datos únicos no estén duplicados.",
                409,
            ) from error
        nombre = {
            "farmacias": "farmacia",
            "productos": "producto",
            "visitas": "visita",
            "pedidos": "pedido",
            "movimientos": "movimiento",
        }[tipo]
        return jsonify({nombre: valores, "duplicado": not creado}), (
            201 if creado else 200
        )

    return app


app = crear_app()


if __name__ == "__main__":
    port = int(os.environ.get("FARMAVISITA_PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
