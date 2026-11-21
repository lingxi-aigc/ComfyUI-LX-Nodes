const GUIDE_PROPERTY = "lxGuideNote";
const MAX_GUIDE_NOTES = 8;
const NOTE_SIZE = [252, 106];
const NOTE_GAP = 22;
const MAX_NOTE_DISTANCE = 440;

const GUIDES = [
    ["model", ["CheckpointLoaderSimple", "CheckpointLoader"], "模型和组件", "选择主模型。MODEL 接采样器，CLIP 接文本编码，VAE 接图像解码。"],
    ["model", ["UNETLoader"], "扩散模型", "选择扩散模型并接入采样器。文本编码器和 VAE 由对应的加载节点提供。"],
    ["input", ["LoadImage", "LoadImageMask"], "输入素材", "在这里替换参考图。局部编辑时，检查图像和遮罩是否接到了对应输入。"],
    ["prompt", ["CLIPTextEncode", "CLIPTextEncodeSDXL"], "提示词条件", "在这里修改文本。沿连线核对它接的是采样器的正面条件还是负面条件。"],
    ["prompt", ["LXText"], "文本输入", "在这里编辑要传给下游的文字。沿连线确认它接到哪一个输入。"],
    ["prompt", ["LXPromptList"], "提示词列表", "在这里编辑各条提示词，连到下游之前先核对输出顺序。"],
    ["prompt", ["LXPromptBatch"], "批量提示词", "检查 TXT 的读取顺序和当前序号，再把提示词接入后续任务。"],
    ["latent", ["EmptyLatentImage", "EmptySD3LatentImage"], "画布与批量", "在这里确认生成宽高和批量。修改尺寸后，检查显存与下游节点要求。"],
    ["sampler", ["KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"], "采样生成", "在这里检查种子和采样设置。局部编辑时，调整降噪幅度以控制改动大小。"],
    ["decode", ["VAEDecode", "VAEDecodeTiled"], "图像解码", "用配套 VAE 把采样结果解码成图像，再接预览或保存。"],
    ["output", ["SaveImage", "LXSaveJPGImage", "LXSaveFolderImage"], "保存输出", "运行前检查保存位置和文件名前缀，避免把不同批次混在一起。"],
    ["output", ["PreviewImage"], "检查结果", "在这里查看结果。需要留存时，把同一路图像接到保存节点。"],
    ["relay", ["LingxiBridgeSettings", "LingxiBridgeApiPool"], "服务配置", "核对服务地址和模型。使用自己的 API Key，分享工作流前先清空密钥输入。"],
    ["sampler", ["LingxiBridgeImage", "LingxiBridgeInpaint"], "服务生成", "检查提示词与参考图。运行会把这些输入提交到你配置的服务。"],
    ["sampler", ["LingxiBatchExecute", "LingxiFolderBatchExecuteSave"], "批量执行", "先用少量任务确认结果，再提高并发。运行后查看状态，定位需要重试的条目。"],
];

const GUIDE_BY_TYPE = new Map(GUIDES.flatMap(([role, types, title, text]) =>
    types.map((type) => [type, { role, title, text }]),
));

function getGraphNodes(graph) {
    return graph?.nodes || graph?._nodes || [];
}

function getGuide(node) {
    return GUIDE_BY_TYPE.get(node?.comfyClass) || GUIDE_BY_TYPE.get(node?.type);
}

export function isGuideNote(node) {
    return (node?.type === "MarkdownNote" || node?.type === "Note") &&
        typeof node.properties?.[GUIDE_PROPERTY]?.targetId === "string";
}

export function isAutoPositionedGuide(node) {
    if (!isGuideNote(node)) return false;
    const previous = node.properties[GUIDE_PROPERTY].position;
    return previous?.[0] === node.pos[0] && previous?.[1] === node.pos[1];
}

export function recordGuidePosition(node) {
    if (isGuideNote(node)) node.properties[GUIDE_PROPERTY].position = [node.pos[0], node.pos[1]];
}

export function collectGuideNotes(graph) {
    const notes = new Map();
    for (const node of getGraphNodes(graph)) {
        if (!isGuideNote(node)) continue;
        const { targetId } = node.properties[GUIDE_PROPERTY];
        if (!notes.has(targetId)) notes.set(targetId, node);
    }
    return notes;
}

function getNodeBounds(node) {
    return node.boundingRect || [node.pos[0], node.pos[1], node.size[0], node.size[1]];
}

function getNewNoteBounds(note, getBounds) {
    note.updateArea?.();
    const [x, y, w, h] = getBounds(note);
    // A detached note's size can omit its title in the layout store.
    const titleHeight = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
    const top = Math.min(y, note.pos[1] - titleHeight);
    return [x, top, Math.max(w, note.size[0]), Math.max(y + h, note.pos[1] + note.size[1]) - top];
}

function intersects(a, b, margin = 6) {
    return a[0] < b[0] + b[2] + margin && a[0] + a[2] + margin > b[0] &&
        a[1] < b[1] + b[3] + margin && a[1] + a[3] + margin > b[1];
}

function fitsInside(box, container) {
    return box[0] >= container[0] + 6 && box[1] >= container[1] + 6 &&
        box[0] + box[2] <= container[0] + container[2] - 6 &&
        box[1] + box[3] <= container[1] + container[3] - 6;
}

function findSpace(target, width, height, obstacles, container = null) {
    const [left, top, targetWidth, targetHeight] = target;
    for (let step = 0; step <= 3; step++) {
        const gap = NOTE_GAP + step * 100;
        for (const [x, y] of [
            [left, top + targetHeight + gap],
            [left, top - height - gap],
            [left + targetWidth - width, top + targetHeight + gap],
            [left + targetWidth - width, top - height - gap],
            [left + targetWidth + gap, top],
            [left - width - gap, top],
        ]) {
            const candidate = [x, y, width, height];
            if (container && !fitsInside(candidate, container)) continue;
            if (!obstacles.some((bounds) => intersects(candidate, bounds))) return candidate;
        }
    }
    return null;
}

function hasConnections(node) {
    return node.inputs?.some((input) => input?.link != null) ||
        node.outputs?.some((output) => output?.links?.length) || false;
}

function placeNote(note, bounds, destination) {
    const x = Math.round(destination[0] - bounds[0] + note.pos[0]);
    const y = Math.round(destination[1] - bounds[1] + note.pos[1]);
    if (typeof note.setPos === "function") note.setPos(x, y);
    else note.pos = [x, y];
    note.updateArea?.();
    recordGuidePosition(note);
}

export function syncGuideNotes(graph, targetNodes, {
    getBounds = getNodeBounds, protectedNodes = new Set(), getObstacles = () => [], getContainer = () => null,
    addMissing = true,
} = {}) {
    let added = 0;
    let moved = 0;
    const graphNodes = [...getGraphNodes(graph)];
    const notes = collectGuideNotes(graph);
    const scopes = targetNodes.filter((node) => getGuide(node) && !protectedNodes.has(node) && !node.pinned);
    const candidates = [...scopes].sort((a, b) => Number(hasConnections(b)) - Number(hasConnections(a)));
    const annotatedRoles = new Set(scopes.filter((node) => notes.has(String(node.id))).map((node) => getGuide(node).role));
    let noteCount = graphNodes.filter(isGuideNote).length;

    for (const target of candidates) {
        const id = String(target.id);
        const guide = getGuide(target);
        let note = notes.get(id);
        const existing = Boolean(note);
        if (existing) {
            if (note.pinned || protectedNodes.has(note) || !isAutoPositionedGuide(note)) continue;
        } else {
            if (!addMissing || noteCount >= MAX_GUIDE_NOTES || annotatedRoles.has(guide.role)) continue;
            const liteGraph = globalThis.LiteGraph;
            note = liteGraph?.createNode?.("MarkdownNote") || liteGraph?.createNode?.("Note");
            const widget = note?.widgets?.find((item) => item.name === "text");
            if (!widget) continue;
            note.title = guide.title;
            widget.value = guide.text;
            note.setSize?.([...NOTE_SIZE]);
            note.properties = { ...note.properties, [GUIDE_PROPERTY]: { targetId: id } };
        }

        const targetBounds = getBounds(target);
        const noteBounds = existing ? getBounds(note) : getNewNoteBounds(note, getBounds);
        const obstacles = graphNodes.filter((node) => node !== note).map((node) => getBounds(node));
        obstacles.push(...getObstacles(target));
        const container = getContainer(target);
        if (existing && (!container || fitsInside(noteBounds, container) || !intersects(noteBounds, container)) &&
            intersects(noteBounds, targetBounds, MAX_NOTE_DISTANCE) &&
            !obstacles.some((rect) => intersects(noteBounds, rect))) continue;

        const width = noteBounds[2];
        const height = noteBounds[3];
        let destination = findSpace(targetBounds, width, height, obstacles, container);
        if (!destination && container) destination = findSpace(targetBounds, width, height, [...obstacles, container]);
        if (!destination) continue;
        placeNote(note, noteBounds, destination);
        if (existing) {
            moved++;
        } else {
            graph.add(note);
            graphNodes.push(note);
            notes.set(id, note);
            annotatedRoles.add(guide.role);
            noteCount++;
            added++;
        }
    }
    return { added, moved };
}
