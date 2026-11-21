/*
 * Derived from cg-use-everywhere (chrisgoringe and contributors), Apache-2.0.
 * Modified for LX-Nodes: naming, localization and ComfyUI integration.
 * See NOTICE and licenses/Apache-2.0.txt for attribution and terms.
 */
import { app } from "../../../../scripts/app.js";
import { ue_callbacks } from "./recursive_callbacks.js";
import { Logger } from "./global_input_utilities.js";
import { shared } from "./shared.js";

export function visible_graph()    { return app.canvas.graph }

export function in_visible_graph(node) { 
    try {
        if (node.graph) return node.graph.id == app.canvas.graph.id
        else if (node.subgraph) return node.subgraph.id == app.canvas.graph.id
        else Logger.log_problem(`in_visible_graph: ${node.id} has no graph or subgraph`)
    } catch (e) {
        Logger.log_error(e)
        return false
    }
}

export function get_subgraph_input_type(graph, slot) { return graph.inputNode.slots[slot].type }
export function link_is_from_subgraph_input(link) { return link.origin_id==-10 }

export function connection_from_output_as_input(node, slot) {
    try {
        return {
            type : node.outputs[slot].type, 
            link : {
                origin_id   : node.id, 
                origin_slot : slot,
            },
        }
    } catch (e) {
        console.error(e)
        return false
    }
}

export function fix_new_subgraph_node(node) {
    try {
        const subgraph = node.subgraph
        subgraph.inputNode.slots.forEach((slot, i)=>{
            slot.linkIds.forEach((lid) => {
                const link = subgraph.links[lid]
                const target = subgraph.getNodeById(link.target_id)
                const slot_name = target.inputs[link.target_slot].name
                const ue_connectable = target.properties.ue_properties.widget_ue_connectable[slot_name]
                if (ue_connectable) {
                    const input_name = node.inputs[i]?.name
                    if (slot_name!=input_name) {
                        Logger.log_problem("In fix_new_subgraph names don't match")
                    } else {
                        node.properties.ue_properties.widget_ue_connectable[input_name] = true
                    }
                }
            })
        })
    } catch (e) {
        Logger.log_error(e, "in fix_new_subgraph")
    }
}

class WrappedIONode {
    constructor(io_node) {
        this.io_node = io_node;
        this.graph = io_node.subgraph;
    }

    connect(output_index, input_node, input_index, afterRerouteId) {
        const output = this.io_node.slots[output_index];
        const input = input_node.inputs?.[input_index];
        if (!output || !input) return;
        if (typeof output.connect === "function") {
            return output.connect(input, input_node, afterRerouteId);
        }

        // Older subgraph slots had no topology-aware connect method.
        const id = ++this.graph.last_link_id;
        const link = new LLink(id, output.type, this.io_node.id ?? -10, output_index, input_node.id, input_index, afterRerouteId);
        if (this.graph.links.set) this.graph.links.set(id, link);
        else this.graph.links[id] = link;
        input.link = id;
        output.linkIds.push(id);
        return link;
    }

    getConnectionPos(is_input, slot_number) {
        if (is_input) {
            return [...this.io_node.slots[slot_number].pos]
        } else {
            Logger.log_problem("WrappedIONode.getConnectionPos called for output - not supported");
        }
    }

}
export function wrap_input(io_node) {
    return new WrappedIONode(io_node);
}
