import sqlite3
from pathlib import Path

from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS farmacias (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    direccion TEXT NOT NULL,
    encargado TEXT NOT NULL DEFAULT '',
    telefono TEXT NOT NULL DEFAULT '',
    observaciones TEXT NOT NULL DEFAULT '',
    fecha_creacion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS productos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    sku TEXT NOT NULL UNIQUE,
    presentacion TEXT NOT NULL,
    precio_unitario REAL NOT NULL CHECK (precio_unitario >= 0),
    existencias INTEGER NOT NULL DEFAULT 0 CHECK (existencias >= 0),
    stock_minimo INTEGER NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    fecha_creacion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visitas (
    id TEXT PRIMARY KEY,
    farmacia_id TEXT NOT NULL REFERENCES farmacias(id),
    fecha_hora TEXT NOT NULL,
    resultado TEXT NOT NULL CHECK (
        resultado IN (
            'realizada', 'encargado_ausente',
            'seguimiento_pendiente', 'no_concretada'
        )
    ),
    comentarios TEXT NOT NULL DEFAULT '',
    proxima_fecha TEXT NOT NULL DEFAULT '',
    fecha_creacion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pedidos (
    id TEXT PRIMARY KEY,
    farmacia_id TEXT NOT NULL REFERENCES farmacias(id),
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (
        estado IN ('borrador', 'registrado', 'enviado', 'cancelado')
    ),
    observaciones TEXT NOT NULL DEFAULT '',
    total REAL NOT NULL CHECK (total >= 0),
    fecha_creacion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detalle_pedido (
    id TEXT PRIMARY KEY,
    pedido_id TEXT NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    producto_id TEXT NOT NULL REFERENCES productos(id),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario REAL NOT NULL CHECK (precio_unitario >= 0)
);

CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id TEXT PRIMARY KEY,
    producto_id TEXT NOT NULL REFERENCES productos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida', 'ajuste')),
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    motivo TEXT NOT NULL,
    fecha TEXT NOT NULL,
    existencia_resultante INTEGER NOT NULL CHECK (existencia_resultante >= 0),
    fecha_creacion TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visitas_farmacia_fecha
    ON visitas(farmacia_id, fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_pedidos_farmacia_fecha
    ON pedidos(farmacia_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_detalle_producto ON detalle_pedido(producto_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto_fecha
    ON movimientos_inventario(producto_id, fecha DESC);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(db_path, timeout=10)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        g.db = conexion
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    conexion = g.pop("db", None)
    if conexion is not None:
        conexion.close()


def init_db() -> None:
    get_db().executescript(SCHEMA)
    get_db().commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
