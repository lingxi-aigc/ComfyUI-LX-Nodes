/*
 * Derived from cg-use-everywhere (chrisgoringe and contributors), Apache-2.0.
 * Modified for LX-Nodes: naming, localization and ComfyUI integration.
 * See NOTICE and licenses/Apache-2.0.txt for attribution and terms.
 */

import { any_restrictions, describe_restrictions } from "./global_input_properties.js";
import { app } from "../../../../scripts/app.js";
import { create } from "./global_input_utilities.js";
import { edit_window } from "./floating_window.js";
import { settingsCache } from "./global_input_cache.js";

const HOVERTIME = 500
var hover_node_id = null
var mouse_pos     = [0,0]

const ue_tooltip_element = create('span', 'ue_tooltip', document.body, {id:'ue_tooltip'})

function show_tooltip() {
    ue_tooltip_element.style.display = "block"
    ue_tooltip_element.style.left = `${mouse_pos[0]+10}px`
    ue_tooltip_element.style.top = `${mouse_pos[1]+5}px`
    ue_tooltip_element.innerHTML = ""
    ue_tooltip_element.appendChild(describe_restrictions(app.canvas.node_over))
    ue_tooltip_element.showing = true
}

function show_on_hover() {
    if (!tooltipable()) return

    if (mouse_pos[0]==app.canvas.mouse[0] && mouse_pos[1]==app.canvas.mouse[1]) {
        show_tooltip()
    } else {
        maybe_show_tooltip()
    }
}

function hide_tooltip() {
    ue_tooltip_element.style.display = "none"
    ue_tooltip_element.showing = false
}

function tooltipable() {
    if (
        (!app.canvas?.node_over)                                             ||
        ( edit_window.showing)                                               ||
        (!settingsCache.getSettingValue('Global Input.Graphics.tooltips')) ||
        (!any_restrictions(app.canvas.node_over))
    ) return false

    return true
}

export function maybe_show_tooltip() {
    if (!tooltipable()) return hide_tooltip()

    mouse_pos = [...app.canvas.mouse]
    hover_node_id = app.canvas.node_over.id
    setTimeout(show_on_hover, HOVERTIME)
}
