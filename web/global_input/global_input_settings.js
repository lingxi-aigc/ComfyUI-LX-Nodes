/*
 * Derived from cg-use-everywhere (chrisgoringe and contributors), Apache-2.0.
 * Modified for LX-Nodes: naming, localization and ComfyUI integration.
 * See NOTICE and licenses/Apache-2.0.txt for attribution and terms.
 */
import { app } from "../../../../scripts/app.js";
import { convert_to_links } from "./global_input_apply.js";
import { Logger, is_UEnode, node_can_broadcast, is_able_to_broadcast } from "./global_input_utilities.js";
import { settingsCache } from "./global_input_cache.js";
import { visible_graph } from "./global_input_subgraph_utils.js";
import { edit_restrictions } from "./global_input_properties_editor.js";
import { i18ify_settings } from "./i18n.js";
import { VERSION, shared } from "./shared.js";
import { for_all_graphs } from "./recursive_callbacks.js";

const _SETTINGS = [
    {
        id: "Global Input.About",
        name: `Version ${VERSION}`,
        type: () => {return document.createElement('span')},
    },  
    {
        id: "Global Input.Graphics.showlinks",
        name: "Show links",
        type: "combo",
        options: [ {value:0, text:"All off"}, {value:1, text:"Selected nodes"}, {value:2, text:"Mouseover node"}, {value:3, text:"Selected and mouseover nodes"}, {value:4, text:"All on"}],
        defaultValue: 3,
        onChange: settingsCache.onSettingChange,
    },      
    {
        id: "Global Input.Graphics.fuzzlinks",
        name: "Statically distinguish global input links",
        type: "boolean",
        tooltip: "Render global input links, when shown, differently from normal links. Much lower performance cost than animation.",
        defaultValue: true,
        onChange: settingsCache.onSettingChange,
    },  
    {
        id: "Global Input.Graphics.animate",
        name: "Animate global input links",
        type: "combo",
        options: [ {value:0, text:"Off"}, {value:1, text:"Dots"}, {value:2, text:"Pulse"}, {value:3, text:"Both"}, ],
        defaultValue: 0,
        onChange: settingsCache.onSettingChange,
        tooltip: "Animating links may have a negative impact on UI performance. Consider using statically distinguish global input links instead."
    },
    {
        id: "Global Input.Graphics.stop_animation_when_running",
        name: "Turn animation off when workflow is running",
        type: "boolean",
        defaultValue: true,
        onChange: settingsCache.onSettingChange,
    },    
    {
        id: "Global Input.Graphics.highlight",
        name: "Highlight connected and connectable inputs",
        type: "boolean",
        defaultValue: true,
        onChange: settingsCache.onSettingChange,
    },
    {
        id: "Global Input.Graphics.preserve edit window position",
        name: "Save restrictions edit window position",
        type: "boolean",
        defaultValue: false,
        onChange: settingsCache.onSettingChange,
        tooltip: "If off, the edit window appears where the mouse is"
    },
    {
        id: "Global Input.Graphics.tooltips",
        name: "Show restrictions as tooltip",
        type: "boolean",
        defaultValue: true,
        onChange: settingsCache.onSettingChange,
    },
    {
        id: "Global Input.Options.connect_to_bypassed",
        name: "Connect to bypassed nodes",
        type: "boolean",
        defaultValue: true,
        onChange: settingsCache.onSettingChange,
        tooltip: "By default global input links are made to the node downstream of bypassed nodes."
    },
    {
        id: "Global Input.Options.logging",
        name: "Logging",
        type: "combo",
        options: [ {value:0, text:"Errors Only"}, {value:1, text:"Problems"}, {value:2, text:"Information"}, {value:3, text:"Detail"}, ],
        defaultValue: 1,
        onChange: settingsCache.onSettingChange,
    },
    {
        id: "Global Input.Options.block_graph_validation",
        name: "Block workflow validation",
        type: "boolean",
        defaultValue: true,
        tooltip: "Turn off workflow validation (which tends to replace global input links with real ones)",
        onChange: settingsCache.onSettingChange,
    },
    {
        id: "Global Input.Options.always_modify_graph",
        name: "Always modify graph",
        type: "boolean",
        defaultValue: false,
        tooltip: "If turned on, global input modifications will apply even if the trigger is unknown. This will enable API exports, but may cause incompatibility with other nodes.",
        onChange: settingsCache.onSettingChange,
    },
    {
        id: "Global Input.Options.use_output_name",
        name: "When connecting, use the output slot's name as the input name",
        type: "boolean",
        defaultValue: false,
        tooltip: "By default the link type is used as the name",
        onChange: settingsCache.onSettingChange,
    },
]

export const SETTINGS = i18ify_settings(_SETTINGS)

const ALWAYS_UNCONNECTABLE_WIDGET_INPUTS = {
    LoadImage: new Set(["image", "upload"]),
    LoadImageMask: new Set(["image", "upload"]),
    LoadImageOutput: new Set(["image", "upload"]),
}

const ui_update_settings = [
    "Global Input.Graphics.showlinks",
    "Global Input.Graphics.fuzzlinks",
    "Global Input.Graphics.animate",
    "Global Input.Graphics.stop_animation_when_running",
    "Global Input.Graphics.highlight",
    "Global Input.Language.language",
]
ui_update_settings.forEach((id) => {
    settingsCache.addCallback(id, () => { app.graph?.change?.() })
})

function show_connectable(submenu_root, node) {
    node.inputs.forEach((input, i) => {
        const current_element = submenu_root?.querySelector(`:nth-child(${i+1})`);
        if (current_element) current_element.style.borderLeft = (is_connectable(node,input.name)) ? "2px solid #484" : "";
    })
}

export function is_connectable(node, input_name){
    if (node.properties.rejects_ue_links) return false
    const input = node.inputs.find(i => i.name==input_name);
    if (!input) {
        Logger.log_error(`Can't find input ${input_name} on node ${node.title}`);
        return false;
    }
    if (input.widget) {
        if (is_always_unconnectable_widget_input(node, input)) {
            delete node.properties?.ue_properties?.widget_ue_connectable?.[input_name]
            return false
        }
        return !!(node.properties?.ue_properties?.widget_ue_connectable?.[input_name])
    } else {
        return ! (node.properties?.ue_properties?.input_ue_unconnectable?.[input_name])
    }
}

function toggle_connectable(node, input_name){
    const input = node.inputs.find(i => i.name==input_name);
    const p = node.properties.ue_properties
    if (input.widget) {
        if (is_always_unconnectable_widget_input(node, input)) {
            delete p.widget_ue_connectable?.[input_name]
            return
        }
        p.widget_ue_connectable[input_name]  = !!!p.widget_ue_connectable?.[input_name];
    } else {
        p.input_ue_unconnectable[input_name] = !!!p.input_ue_unconnectable?.[input_name];
    }  
}

function is_always_unconnectable_widget_input(node, input) {
    const node_class = node?.comfyClass || node?.type || node?.constructor?.comfyClass
    const input_name = input?.widget?.name || input?.name
    return !!ALWAYS_UNCONNECTABLE_WIDGET_INPUTS[node_class]?.has(input_name)
}

function widget_ue_submenu(value, options, e, menu, node) {
    if (!(node.properties.ue_properties)) node.properties.ue_properties = {}
    if (!(node.properties.ue_properties.widget_ue_connectable)) node.properties.ue_properties.widget_ue_connectable = {};
    if (!(node.properties.ue_properties.input_ue_unconnectable)) node.properties.ue_properties.input_ue_unconnectable = {};

    const label_to_name = {}
    node.inputs
        .filter(i => !i.hidden)
        .filter(i => !i.name?.includes('$$'))
        .forEach((input) => { label_to_name[input.label || input.name] = input.name });

    const submenu = new LiteGraph.ContextMenu(
        Object.keys(label_to_name),
        { event: e, callback: function (label) { 
            const name = label_to_name[label];
            toggle_connectable(node, name);
            shared.linkRenderController.mark_link_list_outdated();
            show_connectable(this.parentElement, node)
            return true; // keep open
        },
        parentMenu: menu, node:node}
    )
    show_connectable(submenu.root, node)
}

function show_broadcasting(submenu_root, node) {
    node.outputs.forEach((input, i) => {
        const current_element = submenu_root?.querySelector(`:nth-child(${i+1})`);
        if (current_element) current_element.style.borderLeft = (is_able_to_broadcast(node,input.name)) ? "2px solid #484" : "";
    })
}

function toggle_broadcasting(node, output_name){
    const p = node.properties.ue_properties
    p.output_not_broadcasting[output_name] = !!!p.output_not_broadcasting[output_name]
}

function output_ue_submenu(value, options, e, menu, node) {
    if (!(node.properties.ue_properties)) node.properties.ue_properties = {}
    if (!(node.properties.ue_properties.output_not_broadcasting)) node.properties.ue_properties.output_not_broadcasting = {};
    
    const label_to_name = {}
    node.outputs.forEach((output) => {label_to_name[output.label || output.name] = output.name})
    const submenu = new LiteGraph.ContextMenu(
        Object.keys(label_to_name),
        { event: e, callback: function (label) { 
            const name = label_to_name[label];
            toggle_broadcasting(node, name);
            shared.linkRenderController.mark_link_list_outdated();
            show_broadcasting(this.parentElement, node)
            return true; // keep open
        },
        parentMenu: menu, node:node}
    )
    show_broadcasting(submenu.root, node)
}



export function add_extra_menu_items(node, ioio) {
    if (node.ue_extra_menu_items_added) return
    const getExtraMenuOptions = node.getExtraMenuOptions;
    node.getExtraMenuOptions = function(_, options) {
        getExtraMenuOptions?.apply(this, arguments);
        options.push(null);
        if (node_can_broadcast(this)) {
            add_restrictions_and_convert(options, this);
        }
        if (!is_UEnode(node)) {
            add_input_and_output_settings(options, node)
        }
        options.push(null);
        ioio(options,'callback',`menu option on ${this.id}`);
    }
    node.ue_extra_menu_items_added = true
}


function add_restrictions_and_convert(options, node) {
    options.push(
        {
            content: "Edit restrictions",
            callback: edit_restrictions,
        }        
    )

    options.push(
        {
            content: "Convert to real links",
            callback: async () => {
                const ues = shared.graphAnalyser.analyse_graph(visible_graph());
                if (ues===null) {
                    Logger.log_problem("Convert to real links failed to get ues")
                    alert("Convert failed - press f12 to see the console log")
                } else {
                    convert_to_links(ues, node);
                    if (is_UEnode(node)) {
                        visible_graph().remove(node);
                    } else { 
                        node.properties.ue_convert = false
                    }
                }
            }
        }
    )
}

function add_input_and_output_settings(options, node) {
    const nodeClass = node?.comfyClass || node?.type;
    if (nodeClass === "BroadcastBlock" || nodeClass === "Broadcast Block" || nodeClass === "屏蔽广播") return

    if (node.inputs?.length) {
        options.push(
            {
                content: node.properties.rejects_ue_links ? "Allow global input links" : "Reject global input links",
                has_submenu: false,
                callback: () => { node.properties.rejects_ue_links = !!!node.properties.rejects_ue_links  },
            }
        )

        if (!node.properties.rejects_ue_links) {
            options.push(
                {
                    content: "Global input connectable inputs",
                    has_submenu: true,
                    callback: widget_ue_submenu,
                }            
            )
        }
    }

    if (node.outputs.length) {
        options.push(
            {
                content: node.properties.ue_convert ? "Remove global broadcasting" : "Add global broadcasting",
                has_submenu: false,
                callback: () => { node.properties.ue_convert = !!!node.properties.ue_convert },                
            }
        )
        if (node.properties.ue_convert) {
            options.push(
                    {
                        content: "Broadcasting Outputs",
                        has_submenu: true,
                        callback: output_ue_submenu,                
                    }
                )
        }
    }
}

function remove_ue_nodes(graph) {
    graph._nodes.filter((node)=>is_UEnode(node)).forEach((node)=>{graph.remove(node)})
}

function graph_has_broadcast_nodes(graph) {
    const nodes = graph?.nodes || graph?._nodes || [];
    return nodes.some((node) => node && (node_can_broadcast(node) || graph_has_broadcast_nodes(node.subgraph)));
}

const VIRTUAL_LINKS_LAST_MODE_KEY = "Global Input.Graphics.last_showlinks"

function showlinks_mode() {
    return Number(app.ui.settings.getSettingValue('Global Input.Graphics.showlinks')) || 0
}

function virtual_links_enabled() {
    return showlinks_mode()>0
}

function remember_showlinks_mode(mode) {
    if (mode>0) localStorage.setItem(VIRTUAL_LINKS_LAST_MODE_KEY, `${mode}`)
}

function restored_showlinks_mode() {
    const saved = Number(localStorage.getItem(VIRTUAL_LINKS_LAST_MODE_KEY))
    return [1, 2, 3, 4].includes(saved) ? saved : 3
}

function set_virtual_links_enabled(enabled) {
    if (enabled) {
        app.ui.settings.setSettingValue('Global Input.Graphics.showlinks', restored_showlinks_mode())
    } else {
        remember_showlinks_mode(showlinks_mode())
        app.ui.settings.setSettingValue('Global Input.Graphics.showlinks', 0)
    }
}

export function canvas_menu_settings() {
    const options = []
    options.push(null); // divider
    options.push({
        content: virtual_links_enabled() ? "隐藏虚拟连线" : "显示虚拟连线",
        callback: () => {
            set_virtual_links_enabled(!virtual_links_enabled());
            app.graph.change();
        }
    });
    if (graph_has_broadcast_nodes(app.graph)) {
        options.push({
            content: "全部虚拟连线转真实连线",
            callback: async () => {
                if (window.confirm("这会把所有全局输入虚拟连线转换为真实连线，并删除所有全局输入节点。确定要继续吗？")) {
                    shared.linkRenderController.pause("convert");
                    try {
                        for_all_graphs(shared.graphAnalyser.modify_graph.bind(shared.graphAnalyser))
                        for_all_graphs(remove_ue_nodes)
                    } finally {
                        app.graph.change();
                        shared.linkRenderController.unpause()
                    }
                    
                }
            }
        });
    }
    if (shared.graphAnalyser.ambiguities.length) {
        options.push({
            content: "Show global broadcast clashes",
            callback: async () => { 
                alert(shared.graphAnalyser.ambiguities.join("\n")) 
            }
        })
    }
    options.push(null); // divider
    return options
}

