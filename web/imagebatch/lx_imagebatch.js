import { app } from "../../../../scripts/app.js";
import { api } from "../../../../scripts/api.js";

function roundRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
}

function fitText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (ctx.measureText(value).width <= maxWidth) return value;
    let out = value;
    while (out.length > 1 && ctx.measureText(out + "...").width > maxWidth) {
        out = out.slice(0, -1);
    }
    return out + "...";
}

function restoreWidgetAutoSize(node) {
    for (const widget of node.widgets || []) {
        if (!widget._lxSizeLocked) continue;
        if (widget._lxOriginalComputeSize) {
            widget.computeSize = widget._lxOriginalComputeSize;
        } else {
            delete widget.computeSize;
        }
        delete widget._lxOriginalComputeSize;
        delete widget._lxSizeLocked;
    }
}

function drawProgressPanel(node, ctx, y) {
    const data = node._lxProgress || {};
    const w = node.size?.[0] || 360;
    const x = 14;
    const panelW = Math.max(260, w - x * 2);
    const panelH = 168;
    const total = Number(data.total || 0);
    const ordinal = Number(data.ordinal || 0);
    const percent = total > 0 && ordinal > 0 ? Math.round((ordinal / total) * 100) : 0;
    const current = data.current || "暂无图片";
    const rootPath = data.path || "";

    ctx.save();
    roundRect(ctx, x, y, panelW, panelH, 8);
    ctx.fillStyle = "#181d25";
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = "#58c58f";
    ctx.fillRect(x, y, panelW, 3);

    ctx.font = "bold 15px sans-serif";
    ctx.fillStyle = "#8ee6b5";
    ctx.fillText("进度预览", x + 16, y + 24);

    ctx.font = "11px sans-serif";
    ctx.fillStyle = "#8f98a6";
    ctx.fillText("LX IMAGEBATCH", x + panelW - 104, y + 24);

    ctx.font = "12px sans-serif";
    ctx.fillStyle = "#98a2b3";
    ctx.fillText("路径", x + 16, y + 50);
    ctx.fillStyle = "#d8dde7";
    ctx.fillText(fitText(ctx, rootPath || "未选择路径", panelW - 32), x + 16, y + 70);

    ctx.font = "bold 34px sans-serif";
    ctx.fillStyle = ordinal > 0 ? "#ffffff" : "#8b94a3";
    const countText = ordinal > 0 ? String(ordinal) : "-";
    ctx.fillText(countText, x + 16, y + 118);

    ctx.font = "18px sans-serif";
    ctx.fillStyle = "#98a2b3";
    ctx.fillText(` / ${total} 张`, x + 16 + ctx.measureText(countText).width + 8, y + 118);

    ctx.font = "bold 28px sans-serif";
    ctx.fillStyle = "#ffffff";
    const pctText = `${percent}%`;
    ctx.fillText(pctText, x + panelW - ctx.measureText(pctText).width - 16, y + 116);

    const barX = x + 16;
    const barY = y + 136;
    const barW = panelW - 32;
    const barH = 12;
    roundRect(ctx, barX, barY, barW, barH, 6);
    ctx.fillStyle = "#303846";
    ctx.fill();
    if (percent > 0) {
        roundRect(ctx, barX, barY, Math.max(8, Math.round(barW * percent / 100)), barH, 6);
        ctx.fillStyle = "#58c58f";
        ctx.fill();
    }

    ctx.font = "13px sans-serif";
    ctx.fillStyle = "#98a2b3";
    ctx.fillText("当前", x + 16, y + 168);
    ctx.fillStyle = "#d8dde7";
    ctx.fillText(fitText(ctx, current, panelW - 72), x + 58, y + 168);
    ctx.restore();
}

app.registerExtension({
    name: "LX_ImageBatch.ResetCounter",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "LXImageBatch") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            this._lxProgress = this._lxProgress || {
                ordinal: 0,
                total: 0,
                percent: 0,
                current: "暂无图片",
                path: "",
            };

            this.addWidget("button", "重置计数器", "重置计数器", () => {
                this.resetCounter();
            }, { serialize: false });

            restoreWidgetAutoSize(this);
            app.graph.setDirtyCanvas(true, false);

            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            restoreWidgetAutoSize(this);
            app.graph.setDirtyCanvas(true, false);
            return r;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const progress = message?.lx_progress?.[0] || message?.lx_progress;
            if (progress) {
                this._lxProgress = progress;
                restoreWidgetAutoSize(this);
                app.graph.setDirtyCanvas(true, false);
            }
        };

        nodeType.prototype.resetCounter = async function () {
            try {
                const response = await api.fetchApi("/lx_imagebatch/reset_counter", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ node_id: this.id.toString() }),
                });
                const result = await response.json();
                if (result.status === "success") {
                    console.log("[LX_加载图像（文件夹）] 计数器已重置");
                    this._lxProgress = {
                        ...(this._lxProgress || {}),
                        ordinal: 0,
                        percent: 0,
                        current: "计数器已重置",
                    };
                    app.graph.setDirtyCanvas(true, false);
                } else {
                    console.error("[LX_加载图像（文件夹）] 重置失败:", result.message);
                }
            } catch (error) {
                console.error("[LX_加载图像（文件夹）] 重置请求失败:", error);
            }
        };
    },
});
