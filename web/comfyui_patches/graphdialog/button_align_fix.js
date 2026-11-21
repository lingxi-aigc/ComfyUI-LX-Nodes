const STYLE_ID = "lx-graphdialog-button-align-fix";

if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
/* Fix ComfyUI frontend 1.45.x graphdialog button alignment. */
.litegraph .graphdialog button,
.litegraph .graphdialog button.rounded {
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 1.6em;
    padding: 0 18px;
    line-height: 1;
    text-align: center;
    white-space: nowrap;
}
`;
    document.head.appendChild(style);
}
