/**
 * LingxiBridgeNotice 前端扩展
 *
 * 职责：渲染美化的提示面板。
 * 尺寸由 Python SIZE = (420, 360) 控制，JS 只负责绘图。
 */

import { app } from "../../../../scripts/app.js";

const OUTER_PADDING_X = 24;
const OUTER_PADDING_Y = 8;
const INNER_PADDING_X = 18;
const INNER_PADDING_Y = 14;
const BOX_RADIUS = 12;
const LINE_HEIGHT = 24;
const BOX_TOP_GAP = 8;
const TEXT_FONT = "16px sans-serif";

function wrapText(ctx, text, maxWidth) {
    const chars = Array.from(text || "");
    const lines = [];
    let current = "";
    for (const ch of chars) {
        const next = current + ch;
        if (current && ctx.measureText(next).width > maxWidth) {
            lines.push(current);
            current = ch;
        } else {
            current = next;
        }
    }
    if (current) lines.push(current);
    return lines.length ? lines : [""];
}

function getNoticeLines(node) {
    const message = String(node._noticeMessage || "").replace(/\r\n/g, "\n");
    return message ? message.split("\n") : [""];
}

function getWrappedLines(ctx, node, width) {
    const textWidth = Math.max(40, width - OUTER_PADDING_X * 2 - INNER_PADDING_X * 2);
    return getNoticeLines(node).flatMap(line => wrapText(ctx, line, textWidth));
}

app.registerExtension({
    name: "LingxiBridge.Notice",

    async nodeCreated(node) {
        if (node.comfyClass !== "LingxiBridgeNotice") return;

        node.resizable = true;

        // 记录初始 message（来自 Python）
        const messageW = node.widgets?.find(w => w.name === "message");
        node._noticeMessage = messageW?.value || "";

        // message widget 值变化时更新缓存
        if (messageW) {
            const origCallback = messageW.callback;
            messageW.callback = function (v) {
                node._noticeMessage = v;
                if (origCallback) origCallback.call(this, v);
            };
        }

        // 自定义绘制：深色圆角卡片
        const origDraw = node.draw;
        node.draw = function (ctx) {
            if (origDraw) origDraw.call(this, ctx);

            const [w, h] = this.size || [420, 360];

            ctx.save();
            ctx.fillStyle = "rgba(22, 27, 34, 0.95)";
            ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
            ctx.lineWidth = 1;

            const radius = BOX_RADIUS;
            const x = OUTER_PADDING_X;
            const y = BOX_TOP_GAP;
            const cw = w - OUTER_PADDING_X * 2;
            const ch = h - OUTER_PADDING_Y - BOX_TOP_GAP;

            ctx.beginPath();
            ctx.moveTo(x + radius, y);
            ctx.lineTo(x + cw - radius, y);
            ctx.quadraticCurveTo(x + cw, y, x + cw, y + radius);
            ctx.lineTo(x + cw, y + ch - radius);
            ctx.quadraticCurveTo(x + cw, y + ch, x + cw - radius, y + ch);
            ctx.lineTo(x + radius, y + ch);
            ctx.quadraticCurveTo(x, y + ch, x, y + ch - radius);
            ctx.lineTo(x, y + radius);
            ctx.quadraticCurveTo(x, y, x + radius, y);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
            ctx.font = TEXT_FONT;
            ctx.textBaseline = "top";

            const lines = getWrappedLines(ctx, this, w);
            let ly = y + INNER_PADDING_Y;
            for (const line of lines) {
                ctx.fillText(line, x + INNER_PADDING_X, ly);
                ly += LINE_HEIGHT;
            }

            ctx.restore();
        };
    },
});
