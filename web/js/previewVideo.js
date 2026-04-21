// Based on https://github.com/ArtVentureX/comfyui-animatediff/blob/main/web/js/vid_preview.js
import { app, ANIM_PREVIEW_WIDGET } from "../../../scripts/app.js";
import { createImageHost } from "../../../scripts/ui/imagePreview.js";

const BASE_SIZE = 768;
const NODE_NAMES = new Set([
    "ComfyUI-Seedance Preview Video",
]);

function setVideoDimensions(videoElement, width, height) {
    videoElement.style.width = `${width}px`;
    videoElement.style.height = `${height}px`;
}

function resizeVideoAspectRatio(videoElement, maxWidth, maxHeight) {
    const aspectRatio = videoElement.videoWidth / videoElement.videoHeight;
    let newWidth;
    let newHeight;

    if (videoElement.videoWidth / maxWidth > videoElement.videoHeight / maxHeight) {
        newWidth = maxWidth;
        newHeight = newWidth / aspectRatio;
    } else {
        newHeight = maxHeight;
        newWidth = newHeight * aspectRatio;
    }

    setVideoDimensions(videoElement, newWidth, newHeight);
}

function chainCallback(object, property, callback) {
    if (object == undefined) {
        console.error("Tried to add callback to non-existant object");
        return;
    }

    if (property in object) {
        const originalCallback = object[property];
        object[property] = function () {
            const result = originalCallback.apply(this, arguments);
            callback.apply(this, arguments);
            return result;
        };
    } else {
        object[property] = callback;
    }
}

function addVideoPreview(nodeType) {
    const createVideoNode = (url) => new Promise((resolve) => {
        const videoEl = document.createElement("video");
        videoEl.addEventListener("loadedmetadata", () => {
            videoEl.controls = false;
            videoEl.loop = true;
            videoEl.muted = true;
            resizeVideoAspectRatio(videoEl, BASE_SIZE, BASE_SIZE);
            resolve(videoEl);
        });
        videoEl.addEventListener("error", () => resolve());
        videoEl.src = url;
    });

    nodeType.prototype.onDrawBackground = function (ctx) {
        if (this.flags.collapsed) {
            return;
        }

        const imageURLs = this.images ?? [];
        let imagesChanged = false;

        if (JSON.stringify(this.displayingImages) !== JSON.stringify(imageURLs)) {
            this.displayingImages = imageURLs;
            imagesChanged = true;
        }

        if (!imagesChanged) {
            return;
        }

        if (!imageURLs.length) {
            this.imgs = null;
            this.animatedImages = false;
            return;
        }

        const promises = imageURLs.map((url) => createVideoNode(url));

        Promise.all(promises)
            .then((imgs) => {
                this.imgs = imgs.filter(Boolean);
            })
            .then(() => {
                if (!this.imgs.length) {
                    return;
                }

                this.animatedImages = true;
                const widgetIdx = this.widgets?.findIndex((widget) => widget.name === ANIM_PREVIEW_WIDGET);

                this.size[0] = BASE_SIZE;
                this.size[1] = BASE_SIZE;

                if (widgetIdx > -1) {
                    const widget = this.widgets[widgetIdx];
                    widget.options.host.updateImages(this.imgs);
                } else {
                    const host = createImageHost(this);
                    const widget = this.addDOMWidget(ANIM_PREVIEW_WIDGET, "img", host.el, {
                        host,
                        getHeight: host.getHeight,
                        onDraw: host.onDraw,
                        hideOnZoom: false,
                    });
                    widget.serializeValue = () => ({ height: BASE_SIZE });
                    widget.options.host.updateImages(this.imgs);
                }

                this.imgs.forEach((img) => {
                    if (img instanceof HTMLVideoElement) {
                        img.muted = true;
                        img.autoplay = true;
                        img.play();
                    }
                });

                this.setDirtyCanvas(true, true);
            });
    };

    chainCallback(nodeType.prototype, "onExecuted", function (message) {
        if (message?.video_url) {
            this.images = message.video_url;
            this.setDirtyCanvas(true);
        }
    });
}

app.registerExtension({
    name: "ComfyUISeedanceVideoPreview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.has(nodeData.name)) {
            return;
        }
        addVideoPreview(nodeType);
    },
});
