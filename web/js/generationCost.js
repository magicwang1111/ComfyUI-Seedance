import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

const GENERATION_NODE_NAMES = new Set([
    "ComfyUI-Seedance Text-to-Video",
    "ComfyUI-Seedance First-Frame-to-Video",
    "ComfyUI-Seedance First-Last-Frame-to-Video",
    "ComfyUI-Seedance Asset Model-to-Video",
    "ComfyUI-Seedance Multimodal-to-Video",
]);

function getOrCreateCostWidget(node) {
    let widget = node.widgets?.find((item) => item.name === "seedance_cost");
    if (widget) {
        return widget;
    }

    widget = ComfyWidgets.STRING(
        node,
        "seedance_cost",
        ["STRING", { multiline: true }],
        app,
    ).widget;
    widget.inputEl.readOnly = true;
    widget.inputEl.style.border = "none";
    widget.inputEl.style.backgroundColor = "transparent";
    widget.serialize = false;
    return widget;
}

app.registerExtension({
    name: "ComfyUISeedanceGenerationCost",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!GENERATION_NODE_NAMES.has(nodeData.name)) {
            return;
        }

        const originalOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalOnExecuted?.apply(this, arguments);

            const summary = message?.seedance_cost?.[0];
            if (!summary) {
                return;
            }

            const widget = getOrCreateCostWidget(this);
            widget.value = summary;
            const computedSize = this.computeSize();
            this.setSize([Math.max(this.size[0], 420), Math.max(this.size[1], computedSize[1])]);
            this.setDirtyCanvas(true, true);
        };
    },
});
