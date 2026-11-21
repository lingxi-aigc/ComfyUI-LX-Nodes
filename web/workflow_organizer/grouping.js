const PHASES = [
    {
        title: "模型与素材",
        color: "#586f8f",
        types: [
            "CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader", "CLIPLoader",
            "DualCLIPLoader", "VAELoader", "LoraLoader", "LoraLoaderModelOnly",
            "ControlNetLoader", "LoadImage", "LoadImageMask", "LoadAudio", "LoadVideo",
            "EmptyLatentImage", "EmptySD3LatentImage", "EmptyHunyuanLatentVideo",
            "MultiLoraLoader", "LXFolderImageCount", "LXImageBatch",
        ],
    },
    {
        title: "提示词与条件",
        color: "#5f7f63",
        types: [
            "CLIPTextEncode", "CLIPTextEncodeSDXL", "CLIPTextEncodeSDXLRefiner",
            "ConditioningCombine", "ConditioningConcat", "ConditioningSetArea",
            "ConditioningSetMask", "ControlNetApply", "ControlNetApplyAdvanced",
            "FluxGuidance", "InpaintModelConditioning", "VAEEncode", "VAEEncodeForInpaint",
            "LXText", "LXTextJoin", "LXTextReplace", "LXPromptList", "LXPromptSplitter",
            "LXPromptBatch", "LXQwenTextGenerate", "LXOfflineTranslator",
        ],
    },
    {
        title: "采样与生成",
        color: "#806a9b",
        types: [
            "KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced",
            "KSamplerSelect", "BasicScheduler", "KarrasScheduler", "BasicGuider",
            "CFGGuider", "RandomNoise", "DisableNoise", "LingxiBridgeImage",
            "LingxiBridgeInpaint", "LingxiBridgeConcurrentImage", "AIHubmixSeedreamEdit",
            "LingxiBatchExecute", "LingxiFolderBatchExecuteSave",
        ],
    },
    {
        title: "解码与后处理",
        color: "#8a7057",
        types: [
            "VAEDecode", "VAEDecodeTiled", "ImageScale", "ImageScaleBy",
            "ImageUpscaleWithModel", "ImageCrop", "ImageCompositeMasked", "ImageBlend",
            "AutoCutout", "SemanticCutout", "LXImageCompression", "LXImageResizeBySide",
            "LXImageMultiResizeBySide", "LingxiResultSplit",
        ],
    },
    {
        title: "预览与输出",
        color: "#6f737b",
        types: [
            "PreviewImage", "SaveImage", "SaveAnimatedWEBP", "SaveAnimatedPNG",
            "PreviewAudio", "SaveAudio", "SaveVideo", "VHS_VideoCombine",
            "LXSaveJPGImage", "LXSaveFolderImage", "LXPromptBatchSaveImage",
            "LXImageCompare", "LXShowAny", "LXShowText",
        ],
    },
];

const PHASE_BY_TYPE = new Map(PHASES.flatMap((phase, index) =>
    phase.types.map((type) => [type, index])
));
const SHARED = Symbol("shared");
const MAX_GROUP_SIZE = 8;
const SMALL_GROUP_SIZE = 4;

function phaseOf(node) {
    return PHASE_BY_TYPE.get(node.comfyClass || node.type || node.constructor?.comfyClass);
}

function compareIds(left, right) {
    const a = left.id;
    const b = right.id;
    if (typeof a === "number") return typeof b === "number" ? a - b : -1;
    if (typeof b === "number") return 1;
    const aText = String(a);
    const bText = String(b);
    return aText < bText ? -1 : aText > bText ? 1 : 0;
}

function buildConnections(nodes, links) {
    const byId = new Map(nodes.map((node) => [String(node.id), node]));
    const inputs = new Map(nodes.map((node) => [node, new Set()]));
    const outputs = new Map(nodes.map((node) => [node, new Set()]));
    for (const link of links) {
        if (!link) continue;
        const from = byId.get(String(link.origin_id));
        const to = byId.get(String(link.target_id));
        if (!from || !to || from === to) continue;
        outputs.get(from).add(to);
        inputs.get(to).add(from);
    }
    return { inputs, outputs };
}

function connectedComponents(nodes, inputs, outputs) {
    const allowed = new Set(nodes);
    const visited = new Set();
    const components = [];
    for (const node of nodes) {
        if (visited.has(node)) continue;
        visited.add(node);
        const members = [node];
        for (let i = 0; i < members.length; i++) {
            const member = members[i];
            for (const neighbors of [inputs.get(member), outputs.get(member)]) {
                for (const neighbor of neighbors) {
                    if (visited.has(neighbor) || !allowed.has(neighbor)) continue;
                    visited.add(neighbor);
                    members.push(neighbor);
                }
            }
        }
        if (members.length >= 2) components.push(members.sort(compareIds));
    }
    return components;
}

function splitBranches(nodes, inputs, outputs) {
    const terminals = nodes.filter((node) => !outputs.get(node).size).sort(compareIds);
    if (terminals.length < 2) return [{ nodes, kind: "segment" }];

    // Follow each terminal backward. A node is either private to one terminal
    // or shared by several. Each node changes owner at most twice, even in cycles.
    const owners = new Map(terminals.map((node) => [node, node]));
    const queue = [...terminals];
    for (let i = 0; i < queue.length; i++) {
        const owner = owners.get(queue[i]);
        for (const upstream of inputs.get(queue[i])) {
            const previous = owners.get(upstream);
            if (previous === owner || previous === SHARED) continue;
            owners.set(upstream, previous ? SHARED : owner);
            queue.push(upstream);
        }
    }
    const byOwner = new Map(terminals.map((node) => [node, []]));
    const shared = [];
    const unassigned = [];
    for (const node of nodes) {
        const owner = owners.get(node);
        if (owner === SHARED) shared.push(node);
        else if (owner) byOwner.get(owner).push(node);
        else unassigned.push(node);
    }
    const branches = [...byOwner.values()].filter((members) => members.length >= 2);
    if (branches.length < 2) return [{ nodes, kind: "segment" }];

    // Preview/save siblings with a common source are useful as one output block.
    // Leave isolated tails and unassigned cyclic fragments in-place rather than
    // joining unrelated nodes merely to fill a frame.
    const singleOutputs = [...byOwner.values()]
        .filter(([first, second]) => first && !second && phaseOf(first) === PHASES.length - 1)
        .map(([node]) => node);
    const outputSiblings = new Map();
    for (const node of singleOutputs) {
        const upstream = [...inputs.get(node)].sort(compareIds)[0];
        if (upstream) {
            if (!outputSiblings.has(upstream)) outputSiblings.set(upstream, []);
            outputSiblings.get(upstream).push(node);
        }
    }
    return [
        { nodes: shared, kind: "shared" },
        ...branches.map((members) => ({ nodes: members, kind: "branch" })),
        ...[...outputSiblings.values()].map((members) => ({ nodes: members, kind: "segment" })),
        ...connectedComponents(unassigned, inputs, outputs).map((members) => ({ nodes: members, kind: "segment" })),
    ].filter((entry) => entry.nodes.length >= 2);
}

function executionOrder(nodes, inputs, outputs) {
    const allowed = new Set(nodes);
    const remainingInputs = new Map();
    let ready = [];
    for (const node of nodes) {
        const degree = [...inputs.get(node)].filter((neighbor) => allowed.has(neighbor)).length;
        remainingInputs.set(node, degree);
        if (!degree) ready.push(node);
    }
    const ordered = [];
    const visited = new Set();
    while (ready.length) {
        const next = [];
        ready.sort((a, b) => (phaseOf(a) ?? PHASES.length) - (phaseOf(b) ?? PHASES.length) || compareIds(a, b));
        for (const node of ready) {
            ordered.push(node);
            visited.add(node);
            for (const consumer of outputs.get(node)) {
                if (!allowed.has(consumer)) continue;
                const degree = remainingInputs.get(consumer) - 1;
                remainingInputs.set(consumer, degree);
                if (!degree) next.push(consumer);
            }
        }
        ready = next;
    }
    // Cyclic and cycle-dependent nodes still get a deterministic order.
    return ordered.concat(nodes.filter((node) => !visited.has(node)).sort(compareIds));
}

function phaseSegments(nodes) {
    const segments = [];
    let start = 0;
    while (start < nodes.length) {
        const remaining = nodes.length - start;
        const cap = Math.min(start + MAX_GROUP_SIZE, nodes.length - 2);
        let end = remaining > MAX_GROUP_SIZE ? cap : nodes.length;
        if (remaining > SMALL_GROUP_SIZE) {
            let previous;
            for (let i = start; i <= cap; i++) {
                const phase = phaseOf(nodes[i]);
                if (phase === undefined) continue;
                if (previous !== undefined && phase !== previous && i >= start + 2) {
                    end = i;
                    break;
                }
                previous = phase;
            }
        }
        segments.push(nodes.slice(start, end));
        start = end;
    }
    return segments;
}

function groupStyle(nodes, kind) {
    if (kind === "shared") return { title: "公共准备", color: "#65756b" };
    const counts = PHASES.map(() => 0);
    for (const node of nodes) {
        const phase = phaseOf(node);
        if (phase !== undefined) counts[phase]++;
    }
    const best = Math.max(...counts);
    if (best >= 2 && best * 2 >= nodes.length && counts.indexOf(best) === counts.lastIndexOf(best)) {
        const { title, color } = PHASES[counts.indexOf(best)];
        return { title, color };
    }
    if (!counts[0] && !counts[1] && counts[4]) {
        if (counts[2]) return { title: "生成与输出", color: PHASES[2].color };
        if (counts[3]) return { title: "后处理与输出", color: PHASES[3].color };
    }
    return {
        title: kind === "branch" ? "工作流分支" : "工作流片段",
        color: kind === "branch" ? "#5e7f88" : "#64686f",
    };
}

export function planGroups(nodes, links) {
    const orderedNodes = [...nodes].sort(compareIds);
    const { inputs, outputs } = buildConnections(orderedNodes, links);
    const groups = connectedComponents(orderedNodes, inputs, outputs).flatMap((component) =>
        splitBranches(component, inputs, outputs).flatMap(({ nodes, kind }) =>
            phaseSegments(executionOrder(nodes, inputs, outputs)).map((segment) => ({
                nodes: segment,
                ...groupStyle(segment, kind),
            }))
        )
    );
    const names = new Map();
    for (const group of groups) {
        const count = (names.get(group.title) ?? 0) + 1;
        names.set(group.title, count);
        if (count > 1) group.title += ` ${count}`;
    }
    return groups;
}
