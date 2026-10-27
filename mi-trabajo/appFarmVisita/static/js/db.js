(() => {
  const DB_NAME = "farmavisita-local";
  const DB_VERSION = 1;
  let connection;

  function abrir() {
    if (connection) return Promise.resolve(connection);
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("cache")) {
          db.createObjectStore("cache", { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains("pending")) {
          db.createObjectStore("pending", { keyPath: "key" });
        }
      };
      request.onsuccess = () => {
        connection = request.result;
        connection.onversionchange = () => connection.close();
        resolve(connection);
      };
      request.onerror = () => reject(request.error || new Error("No se pudo abrir IndexedDB."));
    });
  }

  async function operar(storeName, mode, action) {
    const db = await abrir();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, mode);
      const store = transaction.objectStore(storeName);
      let result;
      try {
        result = action(store);
      } catch (error) {
        reject(error);
        return;
      }
      transaction.oncomplete = () => resolve(result && result.result);
      transaction.onerror = () => reject(transaction.error || new Error("Falló IndexedDB."));
      transaction.onabort = () => reject(transaction.error || new Error("Se canceló IndexedDB."));
    });
  }

  const get = (store, key) => operar(store, "readonly", (items) => items.get(key));
  const all = (store) => operar(store, "readonly", (items) => items.getAll());
  const put = (store, value) => operar(store, "readwrite", (items) => items.put(value));
  const remove = (store, key) => operar(store, "readwrite", (items) => items.delete(key));

  window.LocalDB = { get, all, put, remove };
})();
