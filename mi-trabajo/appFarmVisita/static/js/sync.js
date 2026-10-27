(() => {
  const CACHE_PREFIX = "api:";
  const ENDPOINTS = {
    farmacias: "/api/farmacias",
    visitas: "/api/visitas",
    productos: "/api/productos",
    pedidos: "/api/pedidos",
    movimientos: "/api/inventario/movimientos",
  };

  function notificarPendientes() {
    window.dispatchEvent(new CustomEvent("farmavisita:pending"));
  }

  async function getJson(path) {
    try {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error || `Error HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      await LocalDB.put("cache", { key: CACHE_PREFIX + path, data });
      return data;
    } catch (error) {
      if (error.status) throw error;
      const cached = await LocalDB.get("cache", CACHE_PREFIX + path);
      if (cached) return cached.data;
      throw new Error("No hay datos locales guardados para mostrar sin conexión.");
    }
  }

  async function list(path, type) {
    let rows = await getJson(path);
    if (!Array.isArray(rows)) return rows;
    const pending = (await LocalDB.all("pending")).filter((item) => item.type === type);
    const byId = new Map(rows.map((row) => [row.id, row]));
    for (const item of pending) {
      const previous = byId.get(item.id);
      byId.set(item.id, { ...previous, ...item.data, id: item.id, _pending: true });
    }
    return [...byId.values()];
  }

  async function encolar(type, data) {
    if (type === "movimientos") await validarMovimientoLocal(data);
    const item = {
      key: `${type}:${data.id}`,
      type,
      id: data.id,
      data,
      created_at: new Date().toISOString(),
    };
    await LocalDB.put("pending", item);
    if (type === "movimientos") await aplicarMovimientoLocal(data);
    notificarPendientes();
    return { pending: true };
  }

  async function validarMovimientoLocal(movement) {
    const inventory = await LocalDB.get("cache", CACHE_PREFIX + "/api/inventario")
      || await LocalDB.get("cache", CACHE_PREFIX + "/api/productos");
    const product = inventory?.data?.find((item) => item.id === movement.producto_id);
    if (!product) {
      throw new Error("Consulta el inventario en línea antes de registrar movimientos sin conexión.");
    }
    const quantity = Number(movement.cantidad);
    const resulting = movement.tipo === "entrada"
      ? Number(product.existencias) + quantity
      : movement.tipo === "salida"
        ? Number(product.existencias) - quantity
        : quantity;
    if (!Number.isInteger(quantity) || quantity < 0
      || (movement.tipo !== "ajuste" && quantity === 0)
      || resulting < 0) {
      throw new Error("La cantidad del movimiento no es válida o dejaría existencias negativas.");
    }
  }

  async function aplicarMovimientoLocal(movement) {
    const stockKeys = ["/api/inventario", "/api/productos"];
    for (const path of stockKeys) {
      const cached = await LocalDB.get("cache", CACHE_PREFIX + path);
      if (!cached || !Array.isArray(cached.data)) continue;
      const products = cached.data.map((product) => ({ ...product }));
      const product = products.find((item) => item.id === movement.producto_id);
      if (!product) continue;
      const quantity = Number(movement.cantidad);
      if (movement.tipo === "entrada") product.existencias += quantity;
      if (movement.tipo === "salida") product.existencias -= quantity;
      if (movement.tipo === "ajuste") product.existencias = quantity;
      await LocalDB.put("cache", { key: CACHE_PREFIX + path, data: products });
    }
    const movementCache = await LocalDB.get(
      "cache",
      CACHE_PREFIX + ENDPOINTS.movimientos,
    );
    if (movementCache && Array.isArray(movementCache.data)) {
      await LocalDB.put("cache", {
        key: CACHE_PREFIX + ENDPOINTS.movimientos,
        data: [{ ...movement, _pending: true }, ...movementCache.data],
      });
    }
  }

  async function postOrQueue(type, path, data) {
    if (!navigator.onLine) return encolar(type, data);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(result.error || `Error HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.status) throw error;
      return encolar(type, data);
    }
  }

  async function pendientes() {
    return (await LocalDB.all("pending"))
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
  }

  async function actualizarIndicador() {
    const count = (await pendientes()).length;
    const badge = document.getElementById("pending-count");
    if (badge) badge.textContent = `${count} pendiente${count === 1 ? "" : "s"}`;
    return count;
  }

  async function sincronizar() {
    const queue = await pendientes();
    await actualizarIndicador();
    if (!queue.length) {
      window.showToast?.("No hay registros pendientes.");
      return;
    }
    if (!navigator.onLine) {
      window.showToast?.("Sin conexión. Tus datos siguen guardados en este dispositivo.", true);
      return;
    }

    const button = document.getElementById("sync-button");
    if (button) {
      button.disabled = true;
      button.textContent = "Sincronizando...";
    }
    try {
      const response = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          registros: queue.map(({ type, id, data }) => ({ tipo: type, id, datos: data })),
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "No se pudo sincronizar.");

      const resultsById = new Map(
        result.resultados.map((item) => [`${item.tipo}:${item.id}`, item]),
      );
      let saved = 0;
      const errors = [];
      for (const item of queue) {
        const outcome = resultsById.get(`${item.type}:${item.id}`);
        if (outcome?.ok) {
          await LocalDB.remove("pending", item.key);
          saved += 1;
        } else {
          const errorMessage = outcome?.error || "El servidor no confirmó este registro.";
          await LocalDB.put("pending", { ...item, last_error: errorMessage });
          errors.push(errorMessage);
        }
      }
      await actualizarIndicador();
      if (errors.length) {
        window.showToast?.(
          `${saved} sincronizado(s); ${errors.length} requiere(n) corrección. Los datos se conservaron. ${errors[0]}`,
          true,
        );
      } else {
        window.showToast?.(`${saved} registro(s) sincronizado(s) correctamente.`);
      }
      window.dispatchEvent(new CustomEvent("farmavisita:synced"));
    } catch (error) {
      window.showToast?.(
        `No se completó la sincronización. Los datos siguen guardados: ${error.message}`,
        true,
      );
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Sincronizar ahora";
      }
    }
  }

  window.FarmaSync = {
    list,
    postOrQueue,
    pendientes,
    sincronizar,
    actualizarIndicador,
    endpoints: ENDPOINTS,
  };
  window.addEventListener("online", () => {
    window.setConnectionStatus?.();
    sincronizar();
  });
  window.addEventListener("offline", () => window.setConnectionStatus?.());
  window.addEventListener("farmavisita:pending", actualizarIndicador);
})();
