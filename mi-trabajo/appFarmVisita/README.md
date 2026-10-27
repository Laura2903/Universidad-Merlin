# FarmaVisita

Aplicación web local, adaptable a celular, para registrar farmacias, visitas,
productos, pedidos y movimientos físicos de inventario. Está construida con
Python, Flask, SQLite, HTML, CSS y JavaScript; IndexedDB guarda una copia local
en el navegador y el Service Worker conserva el shell de la aplicación para uso
sin conexión.

No incluye productos ni operaciones comerciales de ejemplo. Agrega los datos
reales que estás autorizado a manejar. Las pruebas usan datos ficticios aislados
en una base temporal.

## Requisitos

- Python 3.11 o posterior.
- Navegador moderno.
- No requiere cuentas, servicios externos ni conexión a internet para iniciar
  Flask después de instalar la dependencia.

## Instalación y ejecución en Windows

Abre PowerShell en la raíz del repositorio. Usa el entorno `.venv` que ya existe
ahí; si aún no existe, créalo:

```powershell
py -3 -m venv .venv
```

Activa el entorno e instala Flask:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\mi-trabajo\appFarmVisita\requirements.txt
```

La aplicación crea automáticamente el esquema SQLite en el primer inicio.
Inicia Flask desde la raíz del repositorio:

```powershell
python .\mi-trabajo\appFarmVisita\app.py
```

Abre <http://127.0.0.1:5000>. Mantén la terminal abierta mientras la usas y
detén el servidor con `Ctrl+C`. El servidor de desarrollo se limita a
`127.0.0.1`: no lo publiques directamente en internet.
Si el puerto 5000 ya está ocupado, selecciona el 5001 antes de iniciar:

```powershell
$env:FARMAVISITA_PORT = "5001"
python .\mi-trabajo\appFarmVisita\app.py
```

En ese caso abre <http://127.0.0.1:5001>.

La base de datos central se crea como `farmavisita.sqlite3` junto a `app.py`.
Está excluida de Git. IndexedDB pertenece al perfil y navegador de cada
dispositivo; borrar los datos del navegador antes de sincronizar puede perder
los registros pendientes.

## Pruebas

Desde la raíz del repositorio, activa `.venv` y ejecuta:

```powershell
python -m unittest discover -s .\mi-trabajo\appFarmVisita\tests -v
```

Las pruebas usan una base temporal, comprueban persistencia, validaciones,
operaciones principales, cálculo de totales, movimientos, reportes y
sincronización idempotente. No escriben datos de prueba en la base de uso normal.

## Cómo comprobar el modo sin conexión

1. Inicia la aplicación y ábrela al menos una vez en
   <http://127.0.0.1:5000> para que el Service Worker almacene los archivos.
2. Con conexión, registra una farmacia y un producto. Abre Inventario para que
   el navegador guarde localmente las existencias antes de probar movimientos.
3. En las herramientas de desarrollador del navegador, activa **Network >
   Offline** (o desconecta el equipo). La interfaz debe mostrar **Sin conexión**.
4. Registra una farmacia, una visita y un pedido. Los cambios quedan en
   IndexedDB y aparecen con la etiqueta **Pendiente**.
5. Si registras un movimiento sin conexión, comprueba que el inventario se haya
   consultado previamente. La aplicación evita una salida que deje existencias
   negativas usando la última existencia guardada localmente.
6. Desactiva **Offline**. Al volver la conexión se intenta sincronizar
   automáticamente; también puedes pulsar **Sincronizar ahora**.
7. Comprueba que el contador de pendientes disminuye y vuelve a cargar la
   aplicación. El servidor conserva los datos en SQLite.

El Service Worker permite abrir el shell después de la primera carga; IndexedDB
permite guardar y consultar en el dispositivo. La sincronización con el servidor
es independiente: los datos de un dispositivo no aparecen en otro hasta que el
servidor los reciba. Los registros rechazados por conflictos o validaciones no se
borran de IndexedDB: el mensaje de sincronización indica el problema para
corregirlo.

No se ejecutó una prueba de navegador automatizada que fuerce modo offline. Los
pasos anteriores son la comprobación manual para validar el comportamiento real
del Service Worker y IndexedDB en tu navegador.

## Instalar en un celular

La instalación de PWA y Service Workers requiere un contexto seguro. `localhost`
funciona para probar en la misma computadora; desde un celular, la dirección
`localhost` apunta al propio teléfono, no a tu computadora. Para acceder desde
otro dispositivo configura un entorno local apropiado o un servidor HTTPS con
autenticación; esta versión no implementa autenticación ni debe exponerse así.
Cuando se publique de forma segura, abre la URL HTTPS en el navegador del
celular y elige **Instalar aplicación** o **Agregar a pantalla de inicio**.

## API REST

Las solicitudes y respuestas usan JSON. Los identificadores son UUID generados
por el cliente. Repetir el envío del mismo UUID y los mismos datos es idempotente;
reutilizarlo con contenido distinto produce un conflicto.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/health` | Comprueba Flask y SQLite. |
| GET, POST | `/api/farmacias` | Lista/busca farmacias (`?q=`) y registra una farmacia. |
| PUT | `/api/farmacias/<id>` | Edita los datos de una farmacia. |
| GET, POST | `/api/visitas` | Consulta el historial o registra una visita. |
| GET, POST | `/api/productos` | Consulta catálogo o registra un producto. |
| PUT | `/api/productos/<id>` | Edita producto, precio, mínimo o estado; no altera existencias. |
| GET, POST | `/api/pedidos` | Consulta pedidos o registra pedido y partidas. |
| GET | `/api/inventario` | Consulta productos y existencias físicas. |
| GET, POST | `/api/inventario/movimientos` | Consulta o registra entrada, salida o ajuste. |
| GET | `/api/reportes` | Calcula indicadores; admite `?desde=AAAA-MM-DD&hasta=AAAA-MM-DD`. |
| POST | `/api/sync` | Recibe hasta 100 registros offline y regresa un resultado por registro. |

Ejemplo de sincronización:

```json
{
  "registros": [
    {
      "tipo": "farmacias",
      "id": "UUID",
      "datos": {"id": "UUID", "nombre": "Nombre comercial"}
    }
  ]
}
```

Los tipos admitidos por sincronización son `farmacias`, `productos`, `visitas`,
`pedidos` y `movimientos`. Los registros se procesan en orden de dependencias.
Cada resultado señala `ok`, `duplicado` o el error de validación.

## Decisiones y límites

- SQLite es la fuente central en este equipo; no está disponible en otro
  dispositivo cuando este servidor no tiene conexión.
- Los pedidos registran solicitudes comerciales, no ventas cobradas o entregas.
  Crear un pedido no descuenta existencias.
- Un movimiento de ajuste establece la existencia física al valor indicado
  (incluye cero); una salida debe ser positiva y no puede dejar stock negativo.
- La aplicación no recopila datos de bebés ni clientes y no incluye
  autenticación. Para publicar en red se debe agregar autenticación, HTTPS,
  controles de acceso, respaldo y una configuración segura de servidor.
