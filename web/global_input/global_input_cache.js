/*
 * Derived from cg-use-everywhere (chrisgoringe and contributors), Apache-2.0.
 * Modified for LX-Nodes: naming, localization and ComfyUI integration.
 * See NOTICE and licenses/Apache-2.0.txt for attribution and terms.
 */
import { app } from "../../../../scripts/app.js";

class LocalSettingsCache {
    constructor() {
        this.local_settings = {}
        this.callbacks = {}
    }
    getSettingValue(id) {
        if (this.local_settings[id]===undefined) this.local_settings[id] = app.ui.settings.getSettingValue(id)
        return this.local_settings[id]
    }
    onSettingChange(new_value, old_value) {
        const id = this.id  // this references the setting that has been changed
        settingsCache.local_settings[id] = new_value
        if (settingsCache.callbacks[id]) {
            settingsCache.callbacks[id].forEach((c) => {c(new_value, old_value, this)})
        }
    }
    addCallback(id, callback) {
        if (this.callbacks[id]===undefined) this.callbacks[id] = []
        this.callbacks[id].push(callback)
    }
}

export const settingsCache = new LocalSettingsCache()