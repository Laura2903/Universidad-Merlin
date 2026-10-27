(() => {
  const root = document.getElementById("view-root");
  const toast = document.getElementById("toast");
  const headings = {
    inicio: ["Inicio", "Resumen de la actividad registrada."],
    farmacias: ["Farmacias", "Administra los puntos de venta que visitas."],
    visitas: ["Visitas", "Registra el resultado y el seguimiento de cada visita."],
    productos: ["Productos", "Catálogo comercial y existencias actuales."],
    pedidos: ["Pedidos", "Registra pedidos; no descuentan existencias automáticamente."],
    inventario: ["Inventario", "Existencias físicas y movimientos registrados."],
    reportes: ["Reportes", "Indicadores calculados a partir de los registros guardados."],
  };
  let vista = "inicio";
  let farmaciaEdicion = null;
  let farmaciaHistorial = null;
  let productoEdicion = null;
  let renderVersion = 0;
  let toastTimer;

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const idNuevo = () => crypto.randomUUID();
  const fechaLocal = () => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 16);
  };
  const today = () => new Date().toISOString().slice(0, 10);
  const currency = (amount) => new Intl.NumberFormat("es-MX", {
    style: "currency", currency: "MXN",
  }).format(Number(amount) || 0);

  window.showToast = (message, isError = false) => {
    toast.textContent = message;
    toast.className = `toast visible${isError ? " error" : ""}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.className = "toast"; }, 5000);
  };

  window.setConnectionStatus = () => {
    const online = navigator.onLine;
    document.getElementById("connection-dot").className =
      `connection-dot ${online ? "online" : "offline"}`;
    document.getElementById("connection-label").textContent =
      online ? "En línea" : "Sin conexión";
  };

  const heading = () => {
    const [title, subtitle] = headings[vista];
    return `<header class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div></header>`;
  };

  async function loadList(path, type) {
    return FarmaSync.list(path, type);
  }

  async function safeLoad(path, type) {
    try {
      return await loadList(path, type);
    } catch (error) {
      window.showToast(error.message, true);
      return [];
    }
  }

  function recordCard(title, lines, actions = "") {
    return `<article class="record-card"><div><h3>${title}</h3>${lines.map((line) => `<p>${line}</p>`).join("")}</div>${actions ? `<div class="record-actions">${actions}</div>` : ""}</article>`;
  }

  function empty(text) {
    return `<div class="empty">${escapeHtml(text)}</div>`;
  }

  async function renderInicio(version) {
    const [farmacias, visitas, pedidos, productos, pending] = await Promise.all([
      safeLoad("/api/farmacias", "farmacias"),
      safeLoad("/api/visitas", "visitas"),
      safeLoad("/api/pedidos", "pedidos"),
      safeLoad("/api/productos", "productos"),
      FarmaSync.pendientes(),
    ]);
    if (version !== renderVersion) return;
    const todayVisits = visitas.filter((item) => (item.fecha_hora || "").slice(0, 10) === today()).length;
    const lowStock = productos.filter((item) =>
      Number(item.activo) !== 0 && Number(item.existencias) <= Number(item.stock_minimo));
    const orderTotal = pedidos.reduce((sum, item) => sum + Number(item.total || 0), 0);
    const recent = [...visitas].sort((a, b) =>
      (b.fecha_hora || "").localeCompare(a.fecha_hora || "")).slice(0, 4);
    root.innerHTML = `${heading()}
      <div class="stats-grid">
        <article class="stat-card"><span class="stat-label">Farmacias registradas</span><strong class="stat-value">${farmacias.length}</strong><span class="stat-hint">En este dispositivo y servidor</span></article>
        <article class="stat-card"><span class="stat-label">Visitas de hoy</span><strong class="stat-value">${todayVisits}</strong><span class="stat-hint">Según la fecha del registro</span></article>
        <article class="stat-card"><span class="stat-label">Pedidos</span><strong class="stat-value">${pedidos.length}</strong><span class="stat-hint">Importe registrado: ${currency(orderTotal)}</span></article>
        <article class="stat-card"><span class="stat-label">Existencias bajas</span><strong class="stat-value">${lowStock.length}</strong><span class="stat-hint">${pending.length} pendiente(s) de sincronizar</span></article>
      </div>
      <section class="panel"><h2>Accesos rápidos</h2><div class="quick-actions">
        <button class="button" data-go="visitas" type="button">Registrar visita</button>
        <button class="button" data-go="pedidos" type="button">Crear pedido</button>
        <button class="button button-outline" data-go="inventario" type="button">Consultar inventario</button>
      </div></section>
      <section class="panel"><h2>Visitas recientes</h2><div class="list">
        ${recent.length ? recent.map((item) => recordCard(escapeHtml(item.farmacia_nombre || "Farmacia"), [
          `${escapeHtml(item.resultado)} · ${escapeHtml(item.fecha_hora || "")}`,
          escapeHtml(item.comentarios || "Sin comentarios"),
        ])).join("") : empty("Todavía no hay visitas registradas.")}
      </div></section>
      ${lowStock.length ? `<section class="panel"><h2>Productos con existencias bajas</h2><div class="list">${lowStock.map((item) => recordCard(escapeHtml(item.nombre), [`Existencias: ${item.existencias} · mínimo: ${item.stock_minimo}`])).join("")}</div></section>` : ""}
      <p class="alert">Los importes muestran pedidos registrados; no equivalen a ventas cobradas o entregadas.</p>`;
  }

  async function renderFarmacias(version) {
    const rows = await safeLoad("/api/farmacias", "farmacias");
    if (version !== renderVersion) return;
    const query = document.getElementById("farmacia-search")?.value.trim().toLocaleLowerCase() || "";
    const filtered = rows.filter((item) => item.nombre.toLocaleLowerCase().includes(query));
    const list = filtered.map((item) => recordCard(
      `${escapeHtml(item.nombre)}${item._pending ? ' <span class="badge warning">Pendiente</span>' : ""}`,
      [
        escapeHtml(item.direccion || "Sin dirección"),
        item.encargado ? `Encargado: ${escapeHtml(item.encargado)}` : "",
        item.telefono ? `Tel.: ${escapeHtml(item.telefono)}` : "",
        escapeHtml(item.observaciones || ""),
      ].filter(Boolean),
      `<button class="text-button" data-history-pharmacy="${escapeHtml(item.id)}" type="button">Historial</button><button class="text-button" data-edit-pharmacy="${escapeHtml(item.id)}" type="button">Editar</button>`,
    )).join("");
    let history = "";
    if (farmaciaHistorial) {
      const selected = rows.find((item) => item.id === farmaciaHistorial);
      const [visits, orders, products] = await Promise.all([
        safeLoad("/api/visitas", "visitas"),
        safeLoad("/api/pedidos", "pedidos"),
        safeLoad("/api/productos", "productos"),
      ]);
      if (version !== renderVersion) return;
      const pharmacyVisits = visits.filter((item) => item.farmacia_id === farmaciaHistorial);
      const pharmacyOrders = orders.filter((item) => item.farmacia_id === farmaciaHistorial);
      history = `<section class="panel"><div class="page-heading"><div><h2>Historial: ${escapeHtml(selected?.nombre || "Farmacia")}</h2><p>Visitas y pedidos asociados.</p></div><button class="button button-outline" data-action="close-history" type="button">Cerrar</button></div>
        <h3>Visitas</h3><div class="list">${pharmacyVisits.map((item) => recordCard(escapeHtml(item.resultado), [`${escapeHtml(item.fecha_hora || "")} · ${escapeHtml(item.comentarios || "")}`])).join("") || empty("Sin visitas registradas.")}</div>
        <h3>Pedidos</h3><div class="list">${pharmacyOrders.map((item) => recordCard(`${escapeHtml(item.estado)} · ${currency(item.total || orderClientTotal(item, products))}`, [`${escapeHtml(item.fecha || "")} · ${escapeHtml(item.observaciones || "")}`])).join("") || empty("Sin pedidos registrados.")}</div></section>`;
    }
    root.innerHTML = `${heading()}
      <div class="inline-controls"><input id="farmacia-search" class="search-input" type="search" placeholder="Buscar farmacia por nombre" value="${escapeHtml(query)}"><button class="button" data-action="new-pharmacy" type="button">+ Nueva farmacia</button></div>
      ${farmaciaEdicion ? pharmacyForm(farmaciaEdicion) : ""}
      ${history}
      <div id="pharmacy-list" class="list">${list || empty("No hay farmacias registradas. Agrega una para empezar.")}</div>`;
  }

  function pharmacyForm(item = null) {
    const edit = Boolean(item?.id);
    return `<section class="panel"><h2>${edit ? "Editar farmacia" : "Registrar farmacia"}</h2>
      <form data-form="farmacia" data-id="${edit ? escapeHtml(item.id) : ""}">
        <div class="form-grid">
          <div class="field"><label for="pharmacy-name">Nombre comercial *</label><input id="pharmacy-name" name="nombre" maxlength="120" required value="${escapeHtml(item?.nombre || "")}"></div>
          <div class="field"><label for="pharmacy-address">Dirección</label><input id="pharmacy-address" name="direccion" maxlength="250" value="${escapeHtml(item?.direccion || "")}"></div>
          <div class="field"><label for="pharmacy-manager">Encargado (opcional)</label><input id="pharmacy-manager" name="encargado" maxlength="120" value="${escapeHtml(item?.encargado || "")}"></div>
          <div class="field"><label for="pharmacy-phone">Teléfono comercial (opcional)</label><input id="pharmacy-phone" name="telefono" maxlength="40" value="${escapeHtml(item?.telefono || "")}"></div>
          <div class="field full"><label for="pharmacy-notes">Observaciones</label><textarea id="pharmacy-notes" name="observaciones" maxlength="1000">${escapeHtml(item?.observaciones || "")}</textarea></div>
        </div>
        <div class="form-actions"><button class="button button-outline" data-action="cancel-pharmacy" type="button">Cancelar</button><button class="button" type="submit">${edit ? "Guardar cambios" : "Guardar farmacia"}</button></div>
      </form></section>`;
  }

  async function renderVisitas(version) {
    const [farmacias, visitas] = await Promise.all([
      safeLoad("/api/farmacias", "farmacias"),
      safeLoad("/api/visitas", "visitas"),
    ]);
    if (version !== renderVersion) return;
    const options = farmacias.map((item) =>
      `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nombre)}</option>`).join("");
    const cards = visitas.slice(0, 60).map((item) => recordCard(
      `${escapeHtml(item.farmacia_nombre || farmacias.find((f) => f.id === item.farmacia_id)?.nombre || "Farmacia")} ${item._pending ? '<span class="badge warning">Pendiente</span>' : ""}`,
      [
        `${escapeHtml(item.resultado)} · ${escapeHtml(item.fecha_hora || "")}`,
        item.proxima_fecha ? `Seguimiento: ${escapeHtml(item.proxima_fecha)}` : "",
        escapeHtml(item.comentarios || "Sin comentarios"),
      ].filter(Boolean),
    )).join("");
    root.innerHTML = `${heading()}
      <section class="panel"><h2>Registrar visita</h2>
        ${farmacias.length ? `<form data-form="visita"><div class="form-grid">
          <div class="field"><label>Farmacia *</label><select name="farmacia_id" required>${options}</select></div>
          <div class="field"><label>Fecha y hora *</label><input name="fecha_hora" type="datetime-local" required value="${fechaLocal()}"></div>
          <div class="field"><label>Resultado *</label><select name="resultado" required>
            <option value="realizada">Visita realizada</option><option value="encargado_ausente">Encargado ausente</option><option value="seguimiento_pendiente">Seguimiento pendiente</option><option value="no_concretada">No se pudo concretar</option>
          </select></div>
          <div class="field"><label>Próximo seguimiento</label><input name="proxima_fecha" type="date"></div>
          <div class="field full"><label>Comentarios</label><textarea name="comentarios" maxlength="1000"></textarea></div>
        </div><div class="form-actions"><button class="button" type="submit">Guardar visita</button></div></form>` : empty("Primero registra una farmacia para asociar la visita.")}</section>
      <section class="panel"><h2>Visitas recientes</h2><div class="list">${cards || empty("Todavía no hay visitas registradas.")}</div></section>`;
  }

  async function renderProductos(version) {
    const rows = await safeLoad("/api/productos", "productos");
    if (version !== renderVersion) return;
    const cards = rows.map((item) => recordCard(
      `${escapeHtml(item.nombre)} ${item._pending ? '<span class="badge warning">Pendiente</span>' : ""} ${Number(item.activo) === 0 ? '<span class="badge danger">Inactivo</span>' : ""}`,
      [
        `SKU: ${escapeHtml(item.sku)} · ${escapeHtml(item.presentacion || "Sin presentación")}`,
        `Precio unitario: ${currency(item.precio_unitario)} · Existencias: ${item.existencias}`,
        `Mínimo: ${item.stock_minimo}${Number(item.existencias) <= Number(item.stock_minimo) ? ' · <span class="badge warning">Stock bajo</span>' : ""}`,
      ],
      `<button class="text-button" data-edit-product="${escapeHtml(item.id)}" type="button">Editar</button>`,
    )).join("");
    root.innerHTML = `${heading()}${productoEdicion ? productForm(productoEdicion) : ""}
      <section class="panel"><h2>Agregar producto</h2><form data-form="producto">
        ${productFields()}
        <div class="form-actions"><button class="button" type="submit">Guardar producto</button></div>
      </form></section>
      <section class="panel"><h2>Catálogo</h2><div class="list">${cards || empty("El catálogo está vacío. Agrega los productos reales de tu negocio.")}</div></section>`;
  }

  function productFields(item = null, editing = false) {
    return `<div class="form-grid">
      <div class="field"><label>Nombre del producto *</label><input name="nombre" maxlength="120" required value="${escapeHtml(item?.nombre || "")}"></div>
      <div class="field"><label>Código o SKU *</label><input name="sku" maxlength="60" required value="${escapeHtml(item?.sku || "")}"></div>
      <div class="field"><label>Presentación</label><input name="presentacion" maxlength="120" value="${escapeHtml(item?.presentacion || "")}"></div>
      <div class="field"><label>Precio unitario *</label><input name="precio_unitario" type="number" min="0" step="0.01" required value="${escapeHtml(item?.precio_unitario ?? "")}"></div>
      ${editing ? "" : '<div class="field"><label>Existencias iniciales</label><input name="existencias" type="number" min="0" step="1" value="0"></div>'}
      <div class="field"><label>Existencias mínimas</label><input name="stock_minimo" type="number" min="0" step="1" value="${escapeHtml(item?.stock_minimo ?? 0)}"></div>
      ${editing ? `<div class="field"><label>Estado</label><select name="activo"><option value="true" ${Number(item.activo) ? "selected" : ""}>Activo</option><option value="false" ${!Number(item.activo) ? "selected" : ""}>Inactivo</option></select></div>` : ""}
    </div>`;
  }

  function productForm(item) {
    return `<section class="panel"><h2>Editar producto</h2><form data-form="producto-edit" data-id="${escapeHtml(item.id)}">
      ${productFields(item, true)}
      <div class="form-actions"><button class="button button-outline" data-action="cancel-product" type="button">Cancelar</button><button class="button" type="submit">Guardar cambios</button></div>
    </form></section>`;
  }

  async function renderPedidos(version) {
    const [farmacias, productos, pedidos] = await Promise.all([
      safeLoad("/api/farmacias", "farmacias"),
      safeLoad("/api/productos", "productos"),
      safeLoad("/api/pedidos", "pedidos"),
    ]);
    if (version !== renderVersion) return;
    const activeProducts = productos.filter((item) => Number(item.activo) !== 0);
    const pharmacyOptions = farmacias.map((item) =>
      `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nombre)}</option>`).join("");
    const productOptions = activeProducts.map((item) =>
      `<option value="${escapeHtml(item.id)}" data-price="${escapeHtml(item.precio_unitario)}">${escapeHtml(item.nombre)} · ${currency(item.precio_unitario)}</option>`).join("");
    const cards = pedidos.map((item) => recordCard(
      `${escapeHtml(item.farmacia_nombre || farmacias.find((f) => f.id === item.farmacia_id)?.nombre || "Pedido")} · ${escapeHtml(item.estado || "registrado")} ${item._pending ? '<span class="badge warning">Pendiente</span>' : ""}`,
      [
        `Fecha: ${escapeHtml(item.fecha || "")} · Importe del pedido: ${currency(item.total || orderClientTotal(item, productos))}`,
        (item.productos || []).map((line) => `${escapeHtml(line.producto_nombre || productos.find((p) => p.id === line.producto_id)?.nombre || "Producto")} × ${line.cantidad}`).join(", "),
        escapeHtml(item.observaciones || ""),
      ].filter(Boolean),
    )).join("");
    root.innerHTML = `${heading()}
      <section class="panel"><h2>Crear pedido</h2>
        ${!farmacias.length ? empty("Registra una farmacia antes de crear un pedido.") : !activeProducts.length ? empty("Registra productos activos antes de crear un pedido.") : `
        <form data-form="pedido">
          <div class="form-grid">
            <div class="field"><label>Farmacia *</label><select name="farmacia_id" required>${pharmacyOptions}</select></div>
            <div class="field"><label>Fecha *</label><input name="fecha" type="date" required value="${today()}"></div>
            <div class="field full"><label>Observaciones</label><textarea name="observaciones" maxlength="1000"></textarea></div>
          </div>
          <div class="field" style="margin-top:1rem"><label>Productos del pedido</label><div id="order-lines" class="order-lines"></div></div>
          <div id="order-total" class="total-line">Total estimado: ${currency(0)}</div>
          <div class="form-actions"><button class="button button-outline" data-action="add-line" type="button">+ Agregar producto</button><button class="button" type="submit">Guardar pedido</button></div>
        </form>`}
      </section>
      <section class="panel"><h2>Pedidos recientes</h2><div class="list">${cards || empty("Todavía no hay pedidos registrados.")}</div>
      <p class="alert">Guardar un pedido no descuenta existencias ni confirma entrega o cobro.</p></section>
      <template id="product-options">${productOptions}</template>`;
    const lines = document.getElementById("order-lines");
    if (lines) addProductLine();
  }

  function orderClientTotal(order, products) {
    return (order.productos || []).reduce((total, line) => {
      const product = products.find((item) => item.id === line.producto_id);
      return total + Number(line.cantidad) * Number(line.precio_unitario ?? product?.precio_unitario ?? 0);
    }, 0);
  }

  function addProductLine() {
    const options = document.getElementById("product-options")?.innerHTML || "";
    const line = document.createElement("div");
    line.className = "order-line";
    line.innerHTML = `<div class="field"><label>Producto</label><select class="order-product" required><option value="">Selecciona un producto</option>${options}</select></div>
      <div class="field"><label>Cantidad</label><input class="order-quantity" type="number" min="1" step="1" value="1" required></div>
      <button class="text-button remove-line" data-action="remove-line" type="button">Quitar</button>`;
    document.getElementById("order-lines").append(line);
    updateOrderTotal();
  }

  function updateOrderTotal() {
    const total = [...document.querySelectorAll(".order-line")].reduce((sum, line) => {
      const select = line.querySelector(".order-product");
      const price = Number(select.selectedOptions[0]?.dataset.price || 0);
      const quantity = Number(line.querySelector(".order-quantity").value || 0);
      return sum + price * quantity;
    }, 0);
    const output = document.getElementById("order-total");
    if (output) output.textContent = `Total estimado: ${currency(total)} · El servidor calcula el total final`;
  }

  async function renderInventario(version) {
    const [products, movements] = await Promise.all([
      safeLoad("/api/inventario", "productos"),
      safeLoad("/api/inventario/movimientos", "movimientos"),
    ]);
    if (version !== renderVersion) return;
    const options = products.map((item) =>
      `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nombre)} · ${item.existencias} en existencia</option>`).join("");
    const cards = products.map((item) => recordCard(
      `${escapeHtml(item.nombre)} ${item._pending ? '<span class="badge warning">Pendiente</span>' : ""}`,
      [
        `SKU: ${escapeHtml(item.sku)} · Existencias: ${item.existencias}`,
        `Mínimo: ${item.stock_minimo} ${Number(item.existencias) <= Number(item.stock_minimo) ? '<span class="badge warning">Stock bajo</span>' : ""}`,
      ],
    )).join("");
    const recent = movements.slice(0, 12).map((item) => recordCard(
      `${escapeHtml(item.producto_nombre || products.find((p) => p.id === item.producto_id)?.nombre || "Producto")} · ${escapeHtml(item.tipo)} ${item._pending ? '<span class="badge warning">Pendiente</span>' : ""}`,
      [`Cantidad: ${item.cantidad} · Existencia resultante: ${item.existencia_resultante ?? "por sincronizar"}`, `${escapeHtml(item.fecha || "")} · ${escapeHtml(item.motivo || "")}`],
    )).join("");
    root.innerHTML = `${heading()}
      <section class="panel"><h2>Registrar movimiento</h2>
        ${products.length ? `<form data-form="movimiento"><div class="form-grid">
          <div class="field"><label>Producto *</label><select name="producto_id" required>${options}</select></div>
          <div class="field"><label>Tipo *</label><select name="tipo" required><option value="entrada">Entrada</option><option value="salida">Salida</option><option value="ajuste">Ajuste de existencia</option></select></div>
          <div class="field"><label id="movement-quantity-label">Cantidad *</label><input name="cantidad" type="number" min="1" step="1" required value="1"></div>
          <div class="field"><label>Fecha *</label><input name="fecha" type="date" required value="${today()}"></div>
          <div class="field full"><label>Motivo *</label><input name="motivo" maxlength="250" required></div>
        </div><p class="stat-hint">Un ajuste establece la existencia física al número indicado. No registres pedidos como salidas hasta confirmar el movimiento real.</p>
        <div class="form-actions"><button class="button" type="submit">Guardar movimiento</button></div></form>` : empty("Agrega productos al catálogo antes de registrar inventario.")}
      </section>
      <section class="panel"><h2>Existencias</h2><div class="list">${cards || empty("No hay productos en el catálogo.")}</div></section>
      <section class="panel"><h2>Movimientos recientes</h2><div class="list">${recent || empty("Todavía no hay movimientos.")}</div></section>`;
  }

  async function renderReportes(version) {
    const desde = document.getElementById("report-from")?.value || "";
    const hasta = document.getElementById("report-to")?.value || "";
    try {
      const params = new URLSearchParams();
      if (desde) params.set("desde", desde);
      if (hasta) params.set("hasta", hasta);
      const response = await fetch(`/api/reportes?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No se pudo cargar el reporte.");
      if (version !== renderVersion) return;
      root.innerHTML = `${heading()}
        <section class="panel"><h2>Filtrar por periodo</h2><form id="report-filter" class="inline-controls">
          <label class="field"><span>Desde</span><input id="report-from" type="date" value="${escapeHtml(desde)}"></label>
          <label class="field"><span>Hasta</span><input id="report-to" type="date" value="${escapeHtml(hasta)}"></label>
          <button class="button" type="submit">Aplicar</button>
        </form></section>
        <div class="stats-grid">
          <article class="stat-card"><span class="stat-label">Visitas del periodo</span><strong class="stat-value">${data.visitas}</strong></article>
          <article class="stat-card"><span class="stat-label">Pedidos no cancelados</span><strong class="stat-value">${data.pedidos}</strong></article>
          <article class="stat-card"><span class="stat-label">Importe de pedidos</span><strong class="stat-value">${currency(data.importe_pedidos_registrados)}</strong><span class="stat-hint">No significa venta cobrada o entregada</span></article>
        </div>
        <section class="panel"><h2>Productos más solicitados</h2><div class="list">${data.productos_mas_solicitados.map((item) => recordCard(escapeHtml(item.nombre), [`Unidades pedidas: ${item.unidades}`])).join("") || empty("Sin datos de pedidos.")}</div></section>
        <section class="panel"><h2>Existencias bajas</h2><div class="list">${data.existencias_bajas.map((item) => recordCard(escapeHtml(item.nombre), [`Existencias: ${item.existencias} · mínimo: ${item.stock_minimo}`])).join("") || empty("No hay productos bajo el nivel mínimo.")}</div></section>`;
    } catch (error) {
      if (version !== renderVersion) return;
      root.innerHTML = `${heading()}<section class="panel">${empty(escapeHtml(error.message))}</section>`;
    }
  }

  async function render() {
    const version = ++renderVersion;
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.view === vista);
    });
    if (vista === "inicio") return renderInicio(version);
    if (vista === "farmacias") return renderFarmacias(version);
    if (vista === "visitas") return renderVisitas(version);
    if (vista === "productos") return renderProductos(version);
    if (vista === "pedidos") return renderPedidos(version);
    if (vista === "inventario") return renderInventario(version);
    if (vista === "reportes") return renderReportes(version);
  }

  function cambiarVista(view) {
    if (!headings[view]) return;
    vista = view;
    farmaciaEdicion = null;
    farmaciaHistorial = null;
    productoEdicion = null;
    render();
  }

  function formData(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function asNumber(value) {
    return Number(value);
  }

  async function guardar(form) {
    const type = form.dataset.form;
    const data = formData(form);
    const isEdit = type === "farmacia" && Boolean(form.dataset.id);
    if (isEdit) {
      if (!navigator.onLine) throw new Error("Conéctate para editar registros existentes.");
      const response = await fetch(`/api/farmacias/${encodeURIComponent(form.dataset.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "No se pudo actualizar la farmacia.");
      await LocalDB.put("cache", { key: "api:/api/farmacias", data: await fetch("/api/farmacias").then((r) => r.json()) });
      window.showToast("Farmacia actualizada.");
      farmaciaEdicion = null;
      return;
    }

    if (type === "producto-edit") {
      if (!navigator.onLine) throw new Error("Conéctate para editar productos existentes.");
      data.precio_unitario = asNumber(data.precio_unitario);
      data.stock_minimo = asNumber(data.stock_minimo);
      data.activo = data.activo === "true";
      const response = await fetch(`/api/productos/${encodeURIComponent(form.dataset.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "No se pudo actualizar el producto.");
      productoEdicion = null;
      window.showToast("Producto actualizado.");
      return;
    }

    let path;
    let recordType;
    if (type === "farmacia") {
      recordType = "farmacias";
      path = "/api/farmacias";
      data.id = idNuevo();
      data.fecha_creacion = new Date().toISOString();
    } else if (type === "producto") {
      recordType = "productos";
      path = "/api/productos";
      data.id = idNuevo();
      data.precio_unitario = asNumber(data.precio_unitario);
      data.existencias = asNumber(data.existencias);
      data.stock_minimo = asNumber(data.stock_minimo);
      data.activo = true;
      data.fecha_creacion = new Date().toISOString();
    } else if (type === "visita") {
      recordType = "visitas";
      path = "/api/visitas";
      data.id = idNuevo();
      data.fecha_hora = new Date(data.fecha_hora).toISOString();
      data.fecha_creacion = new Date().toISOString();
    } else if (type === "pedido") {
      recordType = "pedidos";
      path = "/api/pedidos";
      const lineas = [...form.querySelectorAll(".order-line")].map((line) => ({
        producto_id: line.querySelector(".order-product").value,
        cantidad: asNumber(line.querySelector(".order-quantity").value),
      }));
      if (!lineas.length || lineas.some((line) => !line.producto_id)) {
        throw new Error("Selecciona al menos un producto para el pedido.");
      }
      data.id = idNuevo();
      data.estado = "registrado";
      data.productos = lineas;
      data.fecha_creacion = new Date().toISOString();
    } else if (type === "movimiento") {
      recordType = "movimientos";
      path = "/api/inventario/movimientos";
      data.id = idNuevo();
      data.cantidad = asNumber(data.cantidad);
      data.fecha_creacion = new Date().toISOString();
    } else {
      throw new Error("Formulario no reconocido.");
    }

    const result = await FarmaSync.postOrQueue(recordType, path, data);
    window.showToast(
      result.pending
        ? "Guardado en este dispositivo. Se sincronizará cuando vuelva la conexión."
        : "Registro guardado correctamente.",
    );
    form.reset();
  }

  document.getElementById("navigation").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (button) cambiarVista(button.dataset.view);
  });

  document.getElementById("sync-button").addEventListener("click", () => FarmaSync.sincronizar());
  root.addEventListener("click", async (event) => {
    const go = event.target.closest("[data-go]");
    if (go) return cambiarVista(go.dataset.go);
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "new-pharmacy") {
      farmaciaEdicion = { nuevo: true };
      return render();
    }
    if (action === "cancel-pharmacy") {
      farmaciaEdicion = null;
      return render();
    }
    if (action === "close-history") {
      farmaciaHistorial = null;
      return render();
    }
    if (action === "cancel-product") {
      productoEdicion = null;
      return render();
    }
    if (action === "add-line") return addProductLine();
    if (action === "remove-line") {
      event.target.closest(".order-line").remove();
      updateOrderTotal();
      return;
    }
    const pharmacyEdit = event.target.closest("[data-edit-pharmacy]");
    if (pharmacyEdit) {
      const items = await safeLoad("/api/farmacias", "farmacias");
      farmaciaEdicion = items.find((item) => item.id === pharmacyEdit.dataset.editPharmacy);
      return render();
    }
    const pharmacyHistory = event.target.closest("[data-history-pharmacy]");
    if (pharmacyHistory) {
      farmaciaHistorial = pharmacyHistory.dataset.historyPharmacy;
      return render();
    }
    const productEdit = event.target.closest("[data-edit-product]");
    if (productEdit) {
      const items = await safeLoad("/api/productos", "productos");
      productoEdicion = items.find((item) => item.id === productEdit.dataset.editProduct);
      return render();
    }
  });

  root.addEventListener("input", async (event) => {
    if (event.target.id === "farmacia-search") {
      const query = event.target.value.trim().toLocaleLowerCase();
      const rows = await safeLoad("/api/farmacias", "farmacias");
      const filtered = rows.filter((item) => item.nombre.toLocaleLowerCase().includes(query));
      const target = document.getElementById("pharmacy-list");
      if (target) {
        target.innerHTML = filtered.map((item) => recordCard(
          `${escapeHtml(item.nombre)}${item._pending ? ' <span class="badge warning">Pendiente</span>' : ""}`,
          [
            escapeHtml(item.direccion || "Sin dirección"),
            item.encargado ? `Encargado: ${escapeHtml(item.encargado)}` : "",
            item.telefono ? `Tel.: ${escapeHtml(item.telefono)}` : "",
            escapeHtml(item.observaciones || ""),
          ].filter(Boolean),
          `<button class="text-button" data-history-pharmacy="${escapeHtml(item.id)}" type="button">Historial</button><button class="text-button" data-edit-pharmacy="${escapeHtml(item.id)}" type="button">Editar</button>`,
        )).join("") || empty("No hay farmacias que coincidan con la búsqueda.");
      }
    }
    if (event.target.matches(".order-quantity")) updateOrderTotal();
  });
  root.addEventListener("change", (event) => {
    if (event.target.matches(".order-product")) updateOrderTotal();
    if (event.target.name === "tipo" && event.target.closest("form")?.dataset.form === "movimiento") {
      const quantity = event.target.closest("form").elements.cantidad;
      const label = document.getElementById("movement-quantity-label");
      const adjustment = event.target.value === "ajuste";
      quantity.min = adjustment ? "0" : "1";
      if (adjustment && quantity.value === "1") quantity.value = "0";
      if (!adjustment && quantity.value === "0") quantity.value = "1";
      label.textContent = adjustment ? "Existencia final *" : "Cantidad *";
    }
  });
  root.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-form]");
    if (!form) return;
    event.preventDefault();
    try {
      await guardar(form);
      await render();
    } catch (error) {
      window.showToast(error.message, true);
    }
  });
  root.addEventListener("submit", (event) => {
    if (event.target.id === "report-filter") {
      event.preventDefault();
      render();
    }
  });
  root.addEventListener("change", (event) => {
    if (event.target.id === "report-from" || event.target.id === "report-to") return;
  });
  window.addEventListener("farmavisita:synced", render);

  window.setConnectionStatus();
  FarmaSync.actualizarIndicador();
  render();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch((error) => {
      console.error("No se pudo registrar el Service Worker.", error);
    });
  }
})();
