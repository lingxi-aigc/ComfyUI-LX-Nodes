/*
 * Derived from cg-use-everywhere (chrisgoringe and contributors), Apache-2.0.
 * Modified for LX-Nodes: naming, localization and ComfyUI integration.
 * See NOTICE and licenses/Apache-2.0.txt for attribution and terms.
 */
import { app } from "../../../../scripts/app.js";
import { display_name } from "./global_input_classes.js";
import { get_real_node, Logger } from "./global_input_utilities.js";

function getLink(graph, id) {
    if (id == null) return;
    return graph?.getLink?.(id) ?? graph?.links?.get?.(id) ?? graph?.links?.[id];
}

function getInputLink(graph, node, index) {
    const input = node.inputs?.[index];
    if (input && "link" in input) return getLink(graph, input.link);
    if (node.io_node) return getLink(graph, node.io_node.slots?.[index]?.linkIds?.[0]);
    // A SubgraphNode's override resolves an inner output, not its outer input.
    if (input && !node.subgraph) return node.getInputLink?.(index);
}

function connect(output, outputIndex, input, inputIndex, afterRerouteId) {
    if (!output || !input) return;
    if (input.io_node) {
        const outputSlot = output.outputs?.[outputIndex];
        if (!outputSlot) return;
        return input.io_node.slots[inputIndex]?.connect(outputSlot, output, afterRerouteId);
    }
    return output.connect(outputIndex, input, inputIndex, afterRerouteId);
}


function _convert_to_links(ue, added_links, removed_links) {
    const output_node_id = ue.output[0];
    const output_index = ue.output[1];
    const output_node = get_real_node(output_node_id, ue.graph);
    Logger.log_info("Adding links for " + ue.description);
    ue.sending_to.forEach((st) => {
        const input_node_id = st.node.id;
        const input_node = get_real_node(input_node_id, ue.graph);
        const input_index = st.input_index;
        if (!input_node) return;
        const previous = getInputLink(ue.graph, input_node, input_index);
        const original = previous && {
            originId: previous.origin_id, originSlot: previous.origin_slot,
            targetId: previous.target_id, targetSlot: previous.target_slot,
            rerouteId: previous.parentId, graph: ue.graph,
        };
        const new_link = connect(output_node, output_index, input_node, input_index);
        if (original && !getLink(ue.graph, previous.id)) removed_links.push(original);

        if (!new_link)
            console.error("Failed to connect nodes: " +
                          `${output_node_id}[${output_index}] -> ` +
                          `${input_node_id}[${input_index}].`);
        else { // Memorize the links we are adding to remove them later
            if (added_links) {
                new_link.control_node = ue.controller;
                added_links.push(new_link);
            }
            Logger.log_info(`  -> ${display_name(st.node)}, ${st.input.name} ` +
                                           `(${st.node.id}.${st.input_index}) (ID: ${new_link.id})`);
        }
    });
}

export function remove_comfyDynamic_autogrow(graph) {
    graph.nodes.filter((node)=>(node.comfyDynamic?.autogrow)).forEach((node)=>{
        node.__ue_removed_comfyDynamic_autogrow = node.comfyDynamic.autogrow
        node.comfyDynamic.autogrow = {}
    })
    const restorer = function() {
        graph.nodes.filter((node)=>(node.__ue_removed_comfyDynamic_autogrow)).forEach((node)=>{
            node.comfyDynamic.autogrow = node.__ue_removed_comfyDynamic_autogrow
            node.__ue_removed_comfyDynamic_autogrow = undefined
        })
    }
    return { restorer:restorer }
}

export function convert_to_links(ues, control_node, graph) {
    if (control_node) {
        if (!graph) graph = control_node.graph
        return _convert_graph_to_links(graph, ues, control_node.id );
    } else {
        if (!graph) graph = app.graph;
        return _convert_graph_to_links(graph, ues, undefined);
    }
}

function _convert_graph_to_links(graph, ues, control_node_id) {
    if (!ues?.ues) {
        Logger.log_detail('no ues in _convert_graph_to_links')
        return {restorer:function(){}, added_links:[]}
    }
    const added_links = []
    const removed_links = []
    ues.ues.forEach((ue)=> {
        if (control_node_id==undefined || ue.controller.id == control_node_id) _convert_to_links(ue, added_links, removed_links);
    });

    const restorer = function() {
        const links_within_graph_ids = new Set()
        const links_within_subgraph_ids = new Set()
        const links_into_subgraph_ids = new Set()
        const links_out_of_subgraph = new Set()
        const problem_links = new Set()

        const new_subgraph_node = graph.getNodeById(graph.last_node_id);
        const new_subgraph = new_subgraph_node?.subgraph;

        added_links.forEach(added_link => { 
            var id = added_link.id
            try {
                if (getLink(graph, id)) {
                    links_within_graph_ids.add(id);  
                } else { 
                    const inputIndex = new_subgraph?.inputs?.findIndex(input => input.linkIds?.includes(id)) ?? -1;
                    const linkToSubgraphNode = inputIndex < 0 ? null : getInputLink(graph, new_subgraph_node, inputIndex);
                    const linkInSubgraph = getLink(new_subgraph, id);
                    if (linkToSubgraphNode) {
                        links_into_subgraph_ids.add(linkToSubgraphNode.id)
                    } else {
                        if (linkInSubgraph) {
                            if (linkInSubgraph.target_id==-20) {
                                links_out_of_subgraph.add(added_link)
                            } else {
                                links_within_subgraph_ids.add(id)
                            }
                        } else problem_links.add(added_link)
                    }
                }
            } catch (e) {
                problem_links.add(added_link)
                Logger.log_error(e);
            }
        });

        links_out_of_subgraph.forEach((llink)=>{
            const control_node_id = llink.control_node?.id
            const control_node_in_graph = graph.getNodeById(control_node_id)
            if (control_node_in_graph) {
                // the control node is outside, so we should disconnect anything else that is connected to the same output of the subgraph node
                const outputIndex = getLink(new_subgraph, llink.id)?.target_slot;
                new_subgraph_node.outputs[outputIndex]?.links?.forEach((link_id)=>{
                    if (getLink(graph, link_id)?.target_id==control_node_id) {
                        // leave the link to the global input node
                    } else {
                        // remove others
                        links_within_graph_ids.add(link_id)
                    }
                })
            } else {
                // control node is inside, leave the link, since we can't UE connect to the output panel
            }
        })

        links_within_graph_ids.forEach((lid)=>{graph.removeLink(lid)})
        links_into_subgraph_ids.forEach((lid)=>{graph.removeLink(lid)})
        links_within_subgraph_ids.forEach((lid)=>{new_subgraph.removeLink(lid)})

        if (problem_links.size>0) {
            Logger.log_problem("Failed to work out how to remove some temporary links:", problem_links)
        }

        removed_links.forEach(original => {
            const { graph, originId, originSlot, targetId, targetSlot, rerouteId } = original;
            const output = get_real_node(originId, graph);
            const input = get_real_node(targetId, graph);
            connect(output, originSlot, input, targetSlot, rerouteId);
        })
    };

    return {restorer:restorer, added_links:added_links}
}
