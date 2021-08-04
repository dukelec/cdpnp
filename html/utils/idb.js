/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

class Idb {
    constructor(db_name = 'cd', store_list = ['var', 'tmp']) {
        
        let _dbp = new Promise((resolve, reject) => {
            const openreq = indexedDB.open(db_name, 1);
            openreq.onerror = () => reject(openreq.error);
            openreq.onsuccess = () => resolve(openreq.result);
            // First time setup: create an empty object store
            openreq.onupgradeneeded = () => {
                console.log(`db: ${db_name}: create stores: ${store_list}`);
                for (let i in store_list)
                    openreq.result.createObjectStore(store_list[i]);
            };
        });
        
        return (async () => {
            this.db = await _dbp;
            return this;
        })();
    }
    
    trans(store_name, type) {
        let store;
        let _sp = new Promise((resolve, reject) => {
            const transaction = this.db.transaction(store_name, type);
            transaction.oncomplete = () => resolve();
            transaction.onabort = transaction.onerror = () => reject(transaction.error);
            store = transaction.objectStore(store_name);
        });
        return {_sp, store};
    }
    
    async get(store_name, key) {
        let {_sp, store} = this.trans(store_name, 'readonly');
        let req = store.get(key);
        await _sp;
        return req.result;
    }
    async set(store_name, key, value) {
        let {_sp, store} = this.trans(store_name, 'readwrite');
        store.put(value, key);
        await _sp;
    }
    async del(store_name, key) {
        let {_sp, store} = this.trans(store_name, 'readwrite');
        store.delete(key);
        await _sp;
    }
    async clear(store_name) {
        let {_sp, store} = this.trans(store_name, 'readwrite');
        store.clear();
        await _sp;
    }
    async keys(store_name) {
        let {_sp, store} = this.trans(store_name, 'readonly');
        let req = store.getAllKeys();
        await _sp;
        return req.result;
    }
    
    stores() {
        return this.db.objectStoreNames;
    }
}

export { Idb };
