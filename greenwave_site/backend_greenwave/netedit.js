const map = L.map("map").setView([39.92, 32.85], 13);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
}).addTo(map);

const bounds = JSON.parse(localStorage.getItem("selectedBounds") || "null");
let network = JSON.parse(localStorage.getItem("selectedNetwork") || "null");
const urlParams = new URLSearchParams(window.location.search || "");
let currentRegionId = urlParams.get("regionId") ? Number(urlParams.get("regionId")) : null;

if (!bounds) {
    alert("Alan secimi bulunamadi.");
    window.location.href = "index.html";
}

const laneInput = document.getElementById("lane-count");
const aliasNumberInput = document.getElementById("road-alias-number");
const aliasMinusBtn = document.getElementById("alias-minus");
const aliasPlusBtn = document.getElementById("alias-plus");
const panelEl = document.querySelector(".panel");
const panelToggleBtn = document.getElementById("panel-toggle");
const linkTitle = document.getElementById("selected-link");
const linkMeta = document.getElementById("selected-meta");
const turnContainer = document.getElementById("turn-options");
const infoBox = document.getElementById("editor-status");
const revertBtn = document.getElementById("revert-edit");
const tlsMeta = document.getElementById("tls-meta");
const cancelEditBtn = document.getElementById("edit-cancel-btn");
const cameraStage = document.getElementById("camera-stage");
const addCameraBtn = document.getElementById("add-camera-btn");
const closeCameraStageBtn = document.getElementById("close-camera-stage-btn");
const cameraListEl = document.getElementById("camera-list");
const cameraNameInput = document.getElementById("camera-name-input");
const cameraSourceTypeSelect = document.getElementById("camera-source-type");
const cameraFileInput = document.getElementById("camera-file-input");
const cameraUrlInput = document.getElementById("camera-url-input");
const loadCameraUrlBtn = document.getElementById("load-camera-url-btn");
const cameraSourceFileWrap = document.getElementById("camera-source-file-wrap");
const cameraSourceUrlWrap = document.getElementById("camera-source-url-wrap");
const cameraRoadSelect = document.getElementById("camera-road-select");
const linkRoadBtn = document.getElementById("link-road-btn");
const captureFrameBtn = document.getElementById("capture-frame-btn");
const linkedRoadsWrap = document.getElementById("linked-roads-wrap");
const cameraPreviewVideo = document.getElementById("camera-preview-video");
const cameraPreviewImage = document.getElementById("camera-preview-image");
const cameraDrawCanvas = document.getElementById("camera-draw-canvas");
const saveRoadDrawingBtn = document.getElementById("save-road-drawing-btn");
const regionNameInput = document.getElementById("region-name-input");
const regionAddressInput = document.getElementById("region-address-input");
const clearRoadDrawingBtn = document.getElementById("clear-road-drawing-btn");
const exportCameraConfigBtn = document.getElementById("export-camera-config-btn");
const saveCameraStageBtn = document.getElementById("save-camera-stage-btn");
const saveAllBtn = document.getElementById("save-all-btn");
const openCameraSetupBtn = document.getElementById("open-camera-setup");
const cancelEditModal = null;
const cancelEditKeepBtn = null;
const cancelEditConfirmBtn = null;
let cancelEditResolver = null;

const linkStates = new Map();
let selectedLinkId = null;
let segmentMode = {
    active: false,
    stateId: null,
    startHandle: null,
    endHandle: null,
    pendingSelection: null,
    previewLayer: null,
};

let lengthMode = {
    active: false,
    stateId: null,
    startHandle: null,
    endHandle: null,
    pendingSelection: null,
    previewLayer: null,
    geometry: null,
};

const undoStack = [];
const forcedTrafficLights = new Set();
const tlsNodeCoords = new Map();
const tlsMarkers = new Map();
const cameraSetup = {
    exportMeta: null,
    availableRoads: [],
    cameras: [],
    selectedCameraId: null,
    selectedRoadForDrawing: null,
    draftPoints: [],
};

let panelCollapsed = false;
let restoredEditorState = null;

function syncPanelToggleUi() {
    if (!panelToggleBtn) {
        return;
    }
    panelToggleBtn.textContent = panelCollapsed ? "◂" : "▸";
    panelToggleBtn.title = panelCollapsed ? "Show editor panel" : "Hide editor panel";
    panelToggleBtn.setAttribute("aria-label", panelCollapsed ? "Show editor panel" : "Hide editor panel");
}

if (panelToggleBtn && panelEl) {
    panelToggleBtn.addEventListener("click", () => {
        panelCollapsed = !panelCollapsed;
        panelEl.classList.toggle("collapsed", panelCollapsed);
        syncPanelToggleUi();
    });
    syncPanelToggleUi();
}

function setInfo(message, isError = false) {
    infoBox.textContent = message;
    infoBox.dataset.error = isError ? "true" : "false";
}




function registerNodeCoord(nodeId, coord) {
    if (!nodeId || !Array.isArray(coord) || coord.length < 2) {
        return;
    }
    if (!tlsNodeCoords.has(nodeId)) {
        tlsNodeCoords.set(nodeId, [coord[0], coord[1]]);
    }
}

function renderTlsMarkers() {
    Array.from(tlsMarkers.entries()).forEach(([nodeId, marker]) => {
        if (!forcedTrafficLights.has(nodeId)) {
            map.removeLayer(marker);
            tlsMarkers.delete(nodeId);
        }
    });

    forcedTrafficLights.forEach((nodeId) => {
        if (tlsMarkers.has(nodeId)) {
            return;
        }
        const coord = tlsNodeCoords.get(nodeId);
        if (!coord) {
            return;
        }
        const marker = L.circleMarker(coord, {
            radius: 7,
            color: "#7f1d1d",
            weight: 1,
            opacity: 0.45,
            fillColor: "#ef4444",
            fillOpacity: 0.22,
            interactive: false,
        }).addTo(map);
        tlsMarkers.set(nodeId, marker);
    });
}

function updateTlsMeta() {
    if (!tlsMeta) {
        return;
    }
    if (forcedTrafficLights.size === 0) {
        tlsMeta.textContent = "No forced traffic-light junction selected.";
        renderTlsMarkers();
        return;
    }
    tlsMeta.textContent = `Forced traffic-light junctions: ${Array.from(forcedTrafficLights).join(", ")}`;
    renderTlsMarkers();
}

function selectedNodeIds() {
    if (!selectedLinkId) {
        return null;
    }
    const state = getState(selectedLinkId);
    if (!state) {
        return null;
    }
    return {
        startNode: state.base.startNode,
        endNode: state.base.endNode,
    };
}

function addForcedTlsAt(which) {
    const nodes = selectedNodeIds();
    if (!nodes) {
        setInfo("Choose a road first.", true);
        return;
    }
    const nodeId = which === "start" ? nodes.startNode : nodes.endNode;
    if (!nodeId) {
        setInfo("Selected junction could not be resolved.", true);
        return;
    }
    pushHistory();
    forcedTrafficLights.add(nodeId);
    updateTlsMeta();
    setInfo(`Traffic light marker added at ${which} junction (${nodeId}).`);
}

function removeForcedTlsAt(which) {
    const nodes = selectedNodeIds();
    if (!nodes) {
        setInfo("Choose a road first.", true);
        return;
    }
    const nodeId = which === "start" ? nodes.startNode : nodes.endNode;
    if (!nodeId) {
        setInfo("Selected junction could not be resolved.", true);
        return;
    }
    if (!forcedTrafficLights.has(nodeId)) {
        setInfo("That junction is not marked as traffic light.", true);
        return;
    }
    pushHistory();
    forcedTrafficLights.delete(nodeId);
    updateTlsMeta();
    setInfo(`Traffic light marker removed from ${which} junction (${nodeId}).`);
}

function displayId(stateOrLink) {
    return stateOrLink.alias || stateOrLink.id;
}

function aliasNumberFromAlias(alias) {
    const match = String(alias || "").match(/^R(\d+)$/i);
    return match ? Number.parseInt(match[1], 10) : null;
}

function currentAliasNumber() {
    const raw = Number.parseInt(aliasNumberInput.value, 10);
    if (!Number.isInteger(raw) || raw < 1) {
        return null;
    }
    return raw;
}

function setAliasNumberValue(value) {
    if (!Number.isInteger(value) || value < 1) {
        aliasNumberInput.value = "";
        return;
    }
    aliasNumberInput.value = String(value);
}

function styleForLaneCount(laneCount, isSelected) {
    return {
        color: isSelected ? "#1d4ed8" : "#2563eb",
        weight: 2 + laneCount,
        opacity: isSelected ? 1 : 0.78,
    };
}

function cloneLatLng(point) {
    return [point.lat, point.lng];
}

function getState(id) {
    return linkStates.get(id);
}

function getBaseLatLngs(state) {
    return state.base.coords.map((coord) => L.latLng(coord[0], coord[1]));
}

function roadGroupKeyFromId(id) {
    return String(id || "").replace(/#\d+$/, "");
}

function roadSegmentIndex(id) {
    const match = String(id || "").match(/#(\d+)$/);
    return match ? Number.parseInt(match[1], 10) : 0;
}

function getRoadGroupStates(state) {
    const key = roadGroupKeyFromId(state.id);
    return Array.from(linkStates.values())
        .filter((item) => roadGroupKeyFromId(item.id) === key)
        .sort((a, b) => {
            const diff = roadSegmentIndex(a.id) - roadSegmentIndex(b.id);
            return diff !== 0 ? diff : a.id.localeCompare(b.id);
        });
}

function polylineLength(latlngs) {
    let total = 0;
    for (let i = 0; i < latlngs.length - 1; i += 1) {
        total += latlngs[i].distanceTo(latlngs[i + 1]);
    }
    return total;
}

function buildGroupGeometry(groupStates) {
    const merged = [];
    const ranges = [];
    let traversed = 0;

    groupStates.forEach((state, idx) => {
        const latlngs = getBaseLatLngs(state);
        const len = polylineLength(latlngs);

        ranges.push({ state, start: traversed, end: traversed + len, length: len });
        traversed += len;

        if (idx === 0) {
            merged.push(...latlngs);
        } else {
            merged.push(...latlngs.slice(1));
        }
    });

    return { mergedLatLngs: merged, ranges, totalLength: traversed };
}

function activeLocalRange(state) {
    if (state.removed) {
        return null;
    }
    if (state.trimRange) {
        return [Math.max(0, Math.min(1, state.trimRange.fromRatio)), Math.max(0, Math.min(1, state.trimRange.toRatio))].sort((a, b) => a - b);
    }
    return [0, 1];
}

function currentGroupWindow(ranges, totalLength) {
    if (totalLength <= 0) {
        return { fromRatio: 0, toRatio: 1 };
    }

    let min = Infinity;
    let max = -Infinity;

    ranges.forEach((entry) => {
        const local = activeLocalRange(entry.state);
        if (!local) {
            return;
        }
        const [lf, lt] = local;
        const absFrom = entry.start + lf * entry.length;
        const absTo = entry.start + lt * entry.length;
        min = Math.min(min, absFrom);
        max = Math.max(max, absTo);
    });

    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
        return { fromRatio: 0, toRatio: 1 };
    }

    return { fromRatio: min / totalLength, toRatio: max / totalLength };
}

function applyGroupTrimFromRatios(ranges, totalLength, fromRatio, toRatio) {
    const fromAbs = Math.max(0, Math.min(1, fromRatio)) * totalLength;
    const toAbs = Math.max(0, Math.min(1, toRatio)) * totalLength;
    const keepStart = Math.min(fromAbs, toAbs);
    const keepEnd = Math.max(fromAbs, toAbs);

    ranges.forEach((entry) => {
        const overlapStart = Math.max(entry.start, keepStart);
        const overlapEnd = Math.min(entry.end, keepEnd);

        if (overlapEnd - overlapStart <= 1e-6 || entry.length <= 1e-9) {
            entry.state.removed = true;
            entry.state.trimRange = null;
            entry.state.segmentEdits = [];
            return;
        }

        entry.state.removed = false;

        const localFrom = (overlapStart - entry.start) / entry.length;
        const localTo = (overlapEnd - entry.start) / entry.length;
        const clampedFrom = Math.max(0, Math.min(1, localFrom));
        const clampedTo = Math.max(0, Math.min(1, localTo));

        if (clampedFrom <= 1e-6 && clampedTo >= 1 - 1e-6) {
            entry.state.trimRange = null;
        } else {
            entry.state.trimRange = { fromRatio: clampedFrom, toRatio: clampedTo };
        }
    });
}
function handleIcon(role) {
    return L.divIcon({
        className: `segment-handle segment-handle-${role}`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
    });
}

function projectOnPolyline(latlngs, target) {
    const point = map.latLngToLayerPoint(target);
    let best = null;
    let traversed = 0;
    let total = 0;

    for (let i = 0; i < latlngs.length - 1; i += 1) {
        total += latlngs[i].distanceTo(latlngs[i + 1]);
    }

    for (let i = 0; i < latlngs.length - 1; i += 1) {
        const p1 = map.latLngToLayerPoint(latlngs[i]);
        const p2 = map.latLngToLayerPoint(latlngs[i + 1]);
        const seg = p2.subtract(p1);
        const pt = point.subtract(p1);
        const segLen2 = seg.x * seg.x + seg.y * seg.y;
        if (segLen2 === 0) {
            continue;
        }
        const t = Math.max(0, Math.min(1, (pt.x * seg.x + pt.y * seg.y) / segLen2));
        const projected = p1.add(seg.multiplyBy(t));
        const distance = projected.distanceTo(point);

        if (!best || distance < best.distance) {
            const a = latlngs[i];
            const b = latlngs[i + 1];
            const latlng = L.latLng(
                a.lat + (b.lat - a.lat) * t,
                a.lng + (b.lng - a.lng) * t
            );
            const lengthUntil = traversed + a.distanceTo(latlng);
            best = {
                index: i,
                t,
                distance,
                latlng,
                ratio: total === 0 ? 0 : lengthUntil / total,
            };
        }

        traversed += latlngs[i].distanceTo(latlngs[i + 1]);
    }

    return best;
}

function segmentCoords(latlngs, startProjection, endProjection) {
    const ordered = [startProjection, endProjection].sort((a, b) => a.ratio - b.ratio);
    const [start, end] = ordered;
    const segment = [start.latlng];

    for (let i = start.index + 1; i <= end.index; i += 1) {
        segment.push(latlngs[i]);
    }

    segment.push(end.latlng);
    return {
        segment,
        fromRatio: start.ratio,
        toRatio: end.ratio,
        startCoord: cloneLatLng(start.latlng),
        endCoord: cloneLatLng(end.latlng),
    };
}

function clearSegmentHandles() {
    if (segmentMode.startHandle) {
        map.removeLayer(segmentMode.startHandle);
        segmentMode.startHandle = null;
    }
    if (segmentMode.endHandle) {
        map.removeLayer(segmentMode.endHandle);
        segmentMode.endHandle = null;
    }
    if (segmentMode.previewLayer) {
        map.removeLayer(segmentMode.previewLayer);
        segmentMode.previewLayer = null;
    }
}

function clearLengthHandles() {
    if (lengthMode.startHandle) {
        map.removeLayer(lengthMode.startHandle);
        lengthMode.startHandle = null;
    }
    if (lengthMode.endHandle) {
        map.removeLayer(lengthMode.endHandle);
        lengthMode.endHandle = null;
    }
    if (lengthMode.previewLayer) {
        map.removeLayer(lengthMode.previewLayer);
        lengthMode.previewLayer = null;
    }
}

function nextCameraId() {
    return `cam-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

function cameraById(id) {
    return cameraSetup.cameras.find((cam) => cam.id === id) || null;
}

function syncSourceTypeUi() {
    if (!cameraSourceTypeSelect || !cameraSourceFileWrap || !cameraSourceUrlWrap) {
        return;
    }
    const sourceType = cameraSourceTypeSelect.value;
    cameraSourceFileWrap.style.display = sourceType === "file" ? "flex" : "none";
    cameraSourceUrlWrap.style.display = sourceType === "url" ? "flex" : "none";
}

function populateRoadSelect() {
    if (!cameraRoadSelect) {
        return;
    }
    cameraRoadSelect.innerHTML = "";
    cameraSetup.availableRoads.forEach((road) => {
        const option = document.createElement("option");
        option.value = road;
        option.textContent = road;
        cameraRoadSelect.appendChild(option);
    });
}

function fitCanvasToImage() {
    if (!cameraDrawCanvas || !cameraPreviewImage) {
        return;
    }
    const w = Math.round(cameraPreviewImage.naturalWidth || 0);
    const h = Math.round(cameraPreviewImage.naturalHeight || 0);
    if (w <= 0 || h <= 0) {
        return;
    }
    cameraDrawCanvas.width = w;
    cameraDrawCanvas.height = h;
    cameraDrawCanvas.style.width = `${w}px`;
    cameraDrawCanvas.style.height = `${h}px`;
    cameraPreviewImage.style.width = `${w}px`;
    cameraPreviewImage.style.height = `${h}px`;
}

function captureFrameForCamera(camera, options = {}) {
    const quiet = Boolean(options.quiet);
    if (!camera || !cameraPreviewVideo || !cameraPreviewImage) {
        return false;
    }
    const w = cameraPreviewVideo.videoWidth;
    const h = cameraPreviewVideo.videoHeight;
    if (!w || !h) {
        if (!quiet) {
            setInfo("Video frame is not ready yet. Play or seek the video first.", true);
        }
        return false;
    }
    const temp = document.createElement("canvas");
    temp.width = w;
    temp.height = h;
    const tctx = temp.getContext("2d");
    if (!tctx) {
        return false;
    }
    tctx.drawImage(cameraPreviewVideo, 0, 0, w, h);
    camera.frameDataUrl = temp.toDataURL("image/png");
    camera.frameWidth = w;
    camera.frameHeight = h;
    cameraPreviewImage.src = camera.frameDataUrl;
    cameraPreviewImage.style.display = "block";
    cameraPreviewVideo.style.display = "none";
    fitCanvasToImage();
    drawOnCameraCanvas();
    if (!quiet) {
        setInfo("Frame captured. Now draw the selected road.");
    }
    return true;
}

function normalizePoints(points, width, height) {
    if (!Array.isArray(points) || !width || !height) {
        return [];
    }
    return points
        .filter((pt) => Array.isArray(pt) && pt.length >= 2)
        .map((pt) => {
            const x = Number(pt[0]);
            const y = Number(pt[1]);
            if (!Number.isFinite(x) || !Number.isFinite(y)) {
                return null;
            }
            return [Number((x / width).toFixed(6)), Number((y / height).toFixed(6))];
        })
        .filter(Boolean);
}

function tryAutoCaptureFrame(camera) {
    if (!camera || !cameraPreviewVideo) {
        return;
    }
    const hasSource = Boolean(camera.sourcePreviewUrl || cameraPreviewVideo.currentSrc || cameraPreviewVideo.src);
    if (!hasSource || camera.frameDataUrl) {
        return;
    }
    const captured = captureFrameForCamera(camera, { quiet: true });
    if (captured) {
        return;
    }
    // Retry a few times because metadata/frame readiness may lag behind canplay.
    let attempts = 0;
    const maxAttempts = 12;
    const timer = setInterval(() => {
        const camNow = cameraById(cameraSetup.selectedCameraId);
        if (!camNow || camNow.id !== camera.id || camNow.frameDataUrl) {
            clearInterval(timer);
            return;
        }
        attempts += 1;
        const ok = captureFrameForCamera(camNow, { quiet: true });
        if (ok) {
            clearInterval(timer);
            setInfo("Frame auto-captured.");
            return;
        }
        if (attempts >= maxAttempts) {
            clearInterval(timer);
            const src = cameraPreviewVideo.currentSrc || cameraPreviewVideo.src || "(empty)";
            setInfo(`Auto-capture failed. Click 'Recapture Frame' or play video. Source: ${src}`, true);
        }
    }, 300);
}

function drawOnCameraCanvas() {
    if (!cameraDrawCanvas) {
        return;
    }
    const ctx = cameraDrawCanvas.getContext("2d");
    if (!ctx) {
        return;
    }
    ctx.clearRect(0, 0, cameraDrawCanvas.width, cameraDrawCanvas.height);

    const camera = cameraById(cameraSetup.selectedCameraId);
    if (!camera) {
        return;
    }

    Object.entries(camera.roadDrawings || {}).forEach(([roadId, points]) => {
        if (!Array.isArray(points) || points.length < 2) {
            return;
        }
        ctx.beginPath();
        ctx.moveTo(points[0][0], points[0][1]);
        for (let i = 1; i < points.length; i += 1) {
            ctx.lineTo(points[i][0], points[i][1]);
        }
        ctx.closePath();
        ctx.lineWidth = 2;
        ctx.strokeStyle = roadId === cameraSetup.selectedRoadForDrawing ? "#f97316" : "#22c55e";
        ctx.stroke();
    });

    if (cameraSetup.draftPoints.length > 0) {
        ctx.beginPath();
        ctx.moveTo(cameraSetup.draftPoints[0][0], cameraSetup.draftPoints[0][1]);
        for (let i = 1; i < cameraSetup.draftPoints.length; i += 1) {
            ctx.lineTo(cameraSetup.draftPoints[i][0], cameraSetup.draftPoints[i][1]);
        }
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#ef4444";
        ctx.stroke();

        cameraSetup.draftPoints.forEach((pt) => {
            ctx.beginPath();
            ctx.arc(pt[0], pt[1], 3, 0, Math.PI * 2);
            ctx.fillStyle = "#ef4444";
            ctx.fill();
        });
    }
}

function renderLinkedRoads(camera) {
    if (!linkedRoadsWrap) {
        return;
    }
    linkedRoadsWrap.innerHTML = "";
    if (!camera || cameraSetup.availableRoads.length === 0) {
        linkedRoadsWrap.innerHTML = '<span class="camera-note">No roads available.</span>';
        return;
    }
    cameraSetup.availableRoads.forEach((road) => {
        const tag = document.createElement("span");
        tag.className = "road-chip";
        const hasDrawing = Array.isArray(camera.roadDrawings?.[road]) && camera.roadDrawings[road].length >= 3;
        tag.textContent = hasDrawing ? `${road} - selected` : `${road} - pending`;
        linkedRoadsWrap.appendChild(tag);
    });
}

function renderCameraList() {
    if (!cameraListEl) {
        return;
    }
    cameraListEl.innerHTML = "";
    cameraSetup.cameras.forEach((camera, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `camera-item${camera.id === cameraSetup.selectedCameraId ? " active" : ""}`;
        button.textContent = `${index + 1}. ${camera.name || `Camera ${index + 1}`}`;
        button.addEventListener("click", () => selectCamera(camera.id));
        cameraListEl.appendChild(button);
    });
}

function selectCamera(cameraId) {
    const camera = cameraById(cameraId);
    if (!camera) {
        return;
    }
    cameraSetup.selectedCameraId = camera.id;
    cameraSetup.selectedRoadForDrawing = camera.linkedRoads[0] || cameraSetup.availableRoads[0] || null;
    cameraSetup.draftPoints = [];

    if (cameraNameInput) {
        cameraNameInput.value = camera.name || "";
    }
    if (cameraSourceTypeSelect) {
        cameraSourceTypeSelect.value = camera.sourceType || "file";
    }
    syncSourceTypeUi();
    if (cameraUrlInput) {
        cameraUrlInput.value = camera.sourceType === "url" ? (camera.sourceValue || "") : "";
    }

    if (cameraPreviewVideo) {
        const sourceType = (camera.sourceType || "").toLowerCase();
        let previewSrc = camera.sourcePreviewUrl || "";
        if (typeof previewSrc === "string" && previewSrc.startsWith("blob:")) {
            previewSrc = "";
        }
        if (!previewSrc && sourceType === "url") {
            previewSrc = camera.sourceValue || "";
        }
        if (!previewSrc && sourceType === "file" && camera.sourceValue) {
            const srcVal = String(camera.sourceValue || "").trim();
            if (srcVal.includes("/") || srcVal.includes("\\")) {
                previewSrc = `/media?path=${encodeURIComponent(srcVal)}`;
            } else if (currentRegionId) {
                const rel = `runtime_assets/transactions/${currentRegionId}/camera/media/${srcVal}`;
                previewSrc = `/media?path=${encodeURIComponent(rel)}`;
            } else {
                previewSrc = `/media?path=${encodeURIComponent(srcVal)}`;
            }
            camera.sourcePreviewUrl = previewSrc;
        }
        cameraPreviewVideo.src = previewSrc || "";
        cameraPreviewVideo.style.display = previewSrc && !camera.frameDataUrl ? "block" : "none";
    }

    if (cameraPreviewImage) {
        cameraPreviewImage.src = camera.frameDataUrl || "";
        cameraPreviewImage.style.display = camera.frameDataUrl ? "block" : "none";
    }

    if (cameraRoadSelect && cameraSetup.selectedRoadForDrawing) {
        cameraRoadSelect.value = cameraSetup.selectedRoadForDrawing;
    }

    renderLinkedRoads(camera);
    renderCameraList();
    setTimeout(() => {
        tryAutoCaptureFrame(camera);
        fitCanvasToImage();
        drawOnCameraCanvas();
    }, 0);
}

function addCamera() {
    const index = cameraSetup.cameras.length + 1;
    const camera = {
        id: nextCameraId(),
        name: `Camera ${index}`,
        sourceType: "file",
        sourceValue: "",
        sourcePreviewUrl: "",
        linkedRoads: [...cameraSetup.availableRoads],
        frameDataUrl: "",
        frameWidth: null,
        frameHeight: null,
        roadDrawings: {},
        roadDrawingsNormalized: {},
    };
    cameraSetup.cameras.push(camera);
    selectCamera(camera.id);
}

function roadCatalogFromState() {
    const aliases = new Set(
        Array.from(linkStates.values())
            .map((state) => state.alias)
            .filter((alias) => /^R\d+$/i.test(alias))
            .map((alias) => alias.toUpperCase())
    );
    return Array.from(aliases).sort((a, b) => {
        const ai = Number.parseInt(a.slice(1), 10);
        const bi = Number.parseInt(b.slice(1), 10);
        return ai - bi;
    });
}

function openCameraSetupStage(exportPayload) {
    if (!cameraStage) {
        return;
    }
    cameraSetup.exportMeta = exportPayload || null;
    cameraSetup.availableRoads = roadCatalogFromState();
    if (cameraSetup.availableRoads.length === 0) {
        cameraSetup.availableRoads = ["R1", "R2", "R3", "R4"];
    }
    cameraSetup.cameras.forEach((camera) => {
        camera.linkedRoads = [...cameraSetup.availableRoads];
    });
    populateRoadSelect();

    if (cameraSetup.cameras.length === 0) {
        addCamera();
    } else {
        selectCamera(cameraSetup.selectedCameraId || cameraSetup.cameras[0].id);
    }

    cameraStage.classList.add("show");
    cameraStage.setAttribute("aria-hidden", "false");
}

function closeCameraSetupStage() {
    if (!cameraStage) {
        return;
    }
    cameraStage.classList.remove("show");
    cameraStage.setAttribute("aria-hidden", "true");
}

function exportCameraConfigFile(allowEmpty = false) {
    if (cameraSetup.cameras.length === 0 && !allowEmpty) {
        setInfo("Add at least one camera before exporting camera config.", true);
        return;
    }
    const payload = {
        createdAt: new Date().toISOString(),
        exportMeta: cameraSetup.exportMeta,
        cameras: cameraSetup.cameras.map((camera) => ({
            id: camera.id,
            name: camera.name,
            sourceType: camera.sourceType,
            source: camera.sourceValue,
            frameSize: {
                width: Number(camera.frameWidth) || null,
                height: Number(camera.frameHeight) || null,
            },
            linkedRoads: cameraSetup.availableRoads,
            roads: cameraSetup.availableRoads.map((roadId) => camera.roadDrawings[roadId] || []),
            roadDrawings: camera.roadDrawings,
            roadDrawingsNormalized: camera.roadDrawingsNormalized || {},
            roads_json_format: cameraSetup.availableRoads.map((roadId) => camera.roadDrawings[roadId] || []),
        })),
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "camera_config.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
    setInfo("Camera config exported.");
}


function closeCancelEditModal(confirmed) {
    if (!cancelEditModal) {
        return;
    }
    cancelEditModal.classList.remove("show");
    cancelEditModal.setAttribute("aria-hidden", "true");
    if (cancelEditResolver) {
        const done = cancelEditResolver;
        cancelEditResolver = null;
        done(Boolean(confirmed));
    }
}

if (cancelEditKeepBtn && cancelEditConfirmBtn) {
    cancelEditKeepBtn.addEventListener("click", () => closeCancelEditModal(false));
    cancelEditConfirmBtn.addEventListener("click", () => closeCancelEditModal(true));
}

function updateCancelEditButton() {
    if (!cancelEditBtn) {
        return;
    }
    const active = segmentMode.active || lengthMode.active;
    cancelEditBtn.disabled = !active;
}

function updateSegmentModeButton() {
    const btn = document.getElementById("segment-mode");
    if (!btn) {
        return;
    }
    if (!segmentMode.active) {
        btn.textContent = "Start Segment Edit";
        return;
    }
    btn.textContent = "Save Segment Edit";
}

function updateLengthModeButton() {
    const btn = document.getElementById("length-mode");
    if (!btn) {
        return;
    }
    if (!lengthMode.active) {
        btn.textContent = "Start Length Edit";
        return;
    }
    btn.textContent = lengthMode.pendingSelection ? "Save Length Edit" : "Cancel Length Edit";
}

function resetSegmentMode() {
    segmentMode.active = false;
    segmentMode.stateId = null;
    segmentMode.pendingSelection = null;
    clearSegmentHandles();
    updateSegmentModeButton();
    updateCancelEditButton();
}

function resetLengthMode() {
    lengthMode.active = false;
    lengthMode.stateId = null;
    lengthMode.pendingSelection = null;
    lengthMode.geometry = null;
    clearLengthHandles();
    updateLengthModeButton();
    updateCancelEditButton();
}function cloneData(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
}

function captureSnapshot() {
    return {
        selectedLinkId,
        forcedTrafficLights: Array.from(forcedTrafficLights),
        states: Array.from(linkStates.values()).map((state) => ({
            id: state.id,
            alias: state.alias,
            currentLanes: state.currentLanes,
            segmentEdits: cloneData(state.segmentEdits) || [],
            turnRestrictions: cloneData(state.turnRestrictions),
            removed: Boolean(state.removed),
            trimRange: cloneData(state.trimRange),
        })),
    };
}

function captureEditorStatePayload() {
    return {
        regionId: currentRegionId ?? null,
        savedAt: new Date().toISOString(),
        regionName: regionNameInput ? regionNameInput.value : "",
        regionAddress: regionAddressInput ? regionAddressInput.value : "",
        snapshot: captureSnapshot(),
        cameraSetup: {
            cameras: cloneData(cameraSetup.cameras || []),
            selectedCameraId: cameraSetup.selectedCameraId || null,
        },
    };
}

function restoreEditorStatePayload(payload) {
    if (!payload || typeof payload !== "object") {
        return;
    }
    restoredEditorState = payload;
    if (regionNameInput && payload.regionName) {
        regionNameInput.value = payload.regionName;
    }
    if (regionAddressInput && payload.regionAddress) {
        regionAddressInput.value = payload.regionAddress;
    }
    if (payload.cameraSetup && Array.isArray(payload.cameraSetup.cameras)) {
        cameraSetup.cameras = (cloneData(payload.cameraSetup.cameras) || []).map((camera) => ({
            ...camera,
            frameWidth: Number(camera?.frameWidth) || null,
            frameHeight: Number(camera?.frameHeight) || null,
            roadDrawings: camera?.roadDrawings || {},
            roadDrawingsNormalized: camera?.roadDrawingsNormalized || {},
            sourcePreviewUrl: (typeof camera?.sourcePreviewUrl === "string" && camera.sourcePreviewUrl.startsWith("blob:"))
                ? ""
                : (camera?.sourcePreviewUrl || ""),
        }));
        cameraSetup.selectedCameraId = payload.cameraSetup.selectedCameraId || null;
    }
    if (payload.snapshot) {
        restoreSnapshot(payload.snapshot);
    }
}

async function loadEditorStateIfAvailable() {
    if (!currentRegionId) {
        return;
    }
    try {
        const response = await fetch(`/editor_state/${encodeURIComponent(currentRegionId)}`);
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        if (!payload || !payload.state) {
            return;
        }
        restoreEditorStatePayload(payload.state);
        setInfo("Loaded existing editor state for this system.");
    } catch (_err) {
        // Keep silent: editing should still work even if state load fails.
    }
}

function restoreSnapshot(snapshot) {
    if (!snapshot || !Array.isArray(snapshot.states)) {
        return;
    }

    resetSegmentMode();
    resetLengthMode();

    forcedTrafficLights.clear();
    (snapshot.forcedTrafficLights || []).forEach((nodeId) => forcedTrafficLights.add(nodeId));
    updateTlsMeta();



    snapshot.states.forEach((snapState) => {
        const state = getState(snapState.id);
        if (!state) {
            return;
        }

        state.alias = snapState.alias || "";
        state.currentLanes = snapState.currentLanes;
        state.segmentEdits = cloneData(snapState.segmentEdits) || [];
        state.turnRestrictions = cloneData(snapState.turnRestrictions) || null;
        state.removed = Boolean(snapState.removed);
        state.trimRange = cloneData(snapState.trimRange) || null;

        if (state.removed) {
            if (map.hasLayer(state.polyline)) {
                map.removeLayer(state.polyline);
            }
            state.segmentLayers.forEach((layer) => {
                if (map.hasLayer(layer)) {
                    map.removeLayer(layer);
                }
            });
            state.segmentLayers = [];
        } else {
            if (!map.hasLayer(state.polyline)) {
                state.polyline.addTo(map);
            }
            redrawState(state);
        }
    });

    if (snapshot.selectedLinkId) {
        const selected = getState(snapshot.selectedLinkId);
        if (selected && !selected.removed) {
            selectLink(snapshot.selectedLinkId);
            return;
        }
    }

    selectedLinkId = null;
    aliasNumberInput.value = "";
    laneInput.value = "1";
    linkTitle.textContent = "No road selected";
    linkMeta.textContent = "Select a blue road.";
    turnContainer.textContent = "Once a route is chosen, this place will fill up.";

    linkStates.forEach((item) => {
        if (!item.removed) {
            redrawState(item);
        }
    });
}

function pushHistory() {
    undoStack.push(captureSnapshot());
    if (undoStack.length > 100) {
        undoStack.shift();
    }
}

function undoLastEdit() {
    if (undoStack.length === 0) {
        setInfo("Nothing to revert.", true);
        return;
    }

    const snapshot = undoStack.pop();
    restoreSnapshot(snapshot);
    setInfo("Last edit reverted.");
}

function renderPendingSegment(state, startProjection, endProjection) {
    const extracted = segmentCoords(state.polyline.getLatLngs(), startProjection, endProjection);
    segmentMode.pendingSelection = {
        stateId: state.id,
        fromRatio: extracted.fromRatio,
        toRatio: extracted.toRatio,
        startCoord: extracted.startCoord,
        endCoord: extracted.endCoord,
        segmentCoords: extracted.segment.map(cloneLatLng),
    };

    if (segmentMode.previewLayer) {
        map.removeLayer(segmentMode.previewLayer);
    }
    segmentMode.previewLayer = L.polyline(segmentMode.pendingSelection.segmentCoords, {
        color: "#22c55e",
        weight: 8,
        opacity: 0.5,
        dashArray: "8 8",
    }).addTo(map);
    updateSegmentModeButton();
}

function refreshPendingSegmentFromHandles() {
    if (!segmentMode.startHandle || !segmentMode.endHandle || !segmentMode.stateId) {
        return;
    }
    const state = getState(segmentMode.stateId);
    renderPendingSegment(state, segmentMode.startHandle.projection, segmentMode.endHandle.projection);
}

function renderPendingLength(state, startProjection, endProjection) {
    if (!lengthMode.geometry || !lengthMode.geometry.mergedLatLngs || lengthMode.geometry.mergedLatLngs.length < 2) {
        return;
    }

    const extracted = segmentCoords(lengthMode.geometry.mergedLatLngs, startProjection, endProjection);
    lengthMode.pendingSelection = {
        stateId: state.id,
        fromRatio: extracted.fromRatio,
        toRatio: extracted.toRatio,
        segmentCoords: extracted.segment.map(cloneLatLng),
    };

    if (lengthMode.previewLayer) {
        map.removeLayer(lengthMode.previewLayer);
    }
    lengthMode.previewLayer = L.polyline(lengthMode.pendingSelection.segmentCoords, {
        color: "#a855f7",
        weight: 9,
        opacity: 0.45,
        dashArray: "10 8",
    }).addTo(map);
    updateLengthModeButton();
}

function refreshPendingLengthFromHandles() {
    if (!lengthMode.startHandle || !lengthMode.endHandle || !lengthMode.stateId || !lengthMode.geometry) {
        return;
    }
    const state = getState(lengthMode.stateId);
    renderPendingLength(state, lengthMode.startHandle.projection, lengthMode.endHandle.projection);
}

function attachHandleDrag(marker, state, refreshFn, projectionLatLngsGetter = null) {
    marker.on("drag", (event) => {
        const latlngs = projectionLatLngsGetter ? projectionLatLngsGetter() : state.polyline.getLatLngs();
        const projected = projectOnPolyline(latlngs, event.target.getLatLng());
        if (!projected) {
            return;
        }
        event.target.projection = projected;
        event.target.setLatLng(projected.latlng);
        refreshFn();
    });
}

function createSegmentHandle(projection, role, state) {
    const marker = L.marker(projection.latlng, {
        draggable: true,
        icon: handleIcon(role),
    }).addTo(map);
    marker.projection = projection;
    attachHandleDrag(marker, state, refreshPendingSegmentFromHandles);
    return marker;
}

function createLengthHandle(projection, role, state) {
    const marker = L.marker(projection.latlng, {
        draggable: true,
        icon: handleIcon(role),
    }).addTo(map);
    marker.projection = projection;
    attachHandleDrag(marker, state, refreshPendingLengthFromHandles, () => (lengthMode.geometry ? lengthMode.geometry.mergedLatLngs : getBaseLatLngs(state)));
    return marker;
}

function redrawState(state) {
    if (state.removed) {
        if (map.hasLayer(state.polyline)) {
            map.removeLayer(state.polyline);
        }
        state.segmentLayers.forEach((layer) => {
            if (map.hasLayer(layer)) {
                map.removeLayer(layer);
            }
        });
        state.segmentLayers = [];
        return;
    }

    if (!map.hasLayer(state.polyline)) {
        state.polyline.addTo(map);
    }

    const isSelected = state.id === selectedLinkId;
    state.polyline.setStyle(styleForLaneCount(state.currentLanes, isSelected));
    state.polyline.setTooltipContent(`${displayId(state)} | lanes: ${state.currentLanes}`);

    const baseLatLngs = getBaseLatLngs(state);
    const renderedCoords = state.trimRange
        ? slicePolylineByRatio(baseLatLngs, state.trimRange.fromRatio, state.trimRange.toRatio)
        : baseLatLngs.map(cloneLatLng);
    state.polyline.setLatLngs(renderedCoords);

    state.segmentLayers.forEach((layer) => map.removeLayer(layer));
    state.segmentLayers = [];

    state.segmentEdits.forEach((edit) => {
        const overlay = L.polyline(edit.segmentCoords, {
            color: "#0f766e",
            weight: 3 + edit.lanes,
            opacity: 0.95,
            dashArray: "10 6",
        })
            .bindTooltip(`${displayId(state)} segment | lanes: ${edit.lanes}`, { sticky: true })
            .addTo(map);
        state.segmentLayers.push(overlay);
    });
}

function outgoingTargetsFor(state) {
    return network.links
        .map((link) => getState(link.id))
        .filter((targetState) => targetState && !targetState.removed && targetState.base.startNode === state.base.endNode && targetState.id !== state.id);
}

function renderTurnOptions(state) {
    turnContainer.innerHTML = "";
    const outgoing = outgoingTargetsFor(state);

    if (outgoing.length === 0) {
        turnContainer.textContent = "There are no editable exits at the end of this road.";
        return;
    }

    const current = state.turnRestrictions?.allowedTargets || outgoing.map((item) => item.id);
    outgoing.forEach((targetState) => {
        const row = document.createElement("label");
        row.className = "turn-row";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = targetState.id;
        checkbox.checked = current.includes(targetState.id);

        const text = document.createElement("span");
        text.textContent = `${displayId(targetState)} (${targetState.id})`;

        row.appendChild(checkbox);
        row.appendChild(text);
        turnContainer.appendChild(row);
    });
}

function pointAtRatio(latlngs, targetRatio) {
    const clamped = Math.max(0, Math.min(1, Number(targetRatio) || 0));
    let total = 0;
    for (let i = 0; i < latlngs.length - 1; i += 1) {
        total += latlngs[i].distanceTo(latlngs[i + 1]);
    }
    if (total <= 0) {
        return { index: 0, ratio: clamped, latlng: latlngs[0] };
    }

    const targetDistance = clamped * total;
    let traversed = 0;

    for (let i = 0; i < latlngs.length - 1; i += 1) {
        const a = latlngs[i];
        const b = latlngs[i + 1];
        const segLength = a.distanceTo(b);
        if (traversed + segLength >= targetDistance) {
            const remain = targetDistance - traversed;
            const t = segLength <= 0 ? 0 : remain / segLength;
            return {
                index: i,
                ratio: clamped,
                latlng: L.latLng(a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t),
            };
        }
        traversed += segLength;
    }

    return { index: latlngs.length - 2, ratio: clamped, latlng: latlngs[latlngs.length - 1] };
}

function slicePolylineByRatio(latlngs, fromRatio, toRatio) {
    const ordered = [Math.max(0, Math.min(1, fromRatio)), Math.max(0, Math.min(1, toRatio))].sort((a, b) => a - b);
    const startProjection = pointAtRatio(latlngs, ordered[0]);
    const endProjection = pointAtRatio(latlngs, ordered[1]);
    const extracted = segmentCoords(latlngs, startProjection, endProjection);
    return extracted.segment.map(cloneLatLng);
}

function selectLink(id) {
    selectedLinkId = id;
    const state = getState(id);

    linkStates.forEach((item) => redrawState(item));

    laneInput.value = state.currentLanes;
    setAliasNumberValue(aliasNumberFromAlias(state.alias));
    linkTitle.textContent = displayId(state);
    linkMeta.textContent = `${state.base.highway}${state.base.name ? ` | ${state.base.name}` : ""} | SUMO: ${state.id}`;
    const groupCount = getRoadGroupStates(state).length;
    renderTurnOptions(state);
    resetSegmentMode();
    resetLengthMode();


    setInfo(`Route selected. Linked segments in this logical road: ${groupCount}.`);
}

function attachLink(link) {
    const polyline = L.polyline(link.coords, styleForLaneCount(link.lanes, false)).addTo(map);
    polyline.bindTooltip(`${link.id} | lanes: ${link.lanes}`, { sticky: true });

    registerNodeCoord(link.startNode, link.coords[0]);
    registerNodeCoord(link.endNode, link.coords[link.coords.length - 1]);

    const state = {
        id: link.id,
        alias: "",
        base: link,
        currentLanes: link.lanes,
        polyline,
        segmentEdits: [],
        segmentLayers: [],
        turnRestrictions: null,
        removed: false,
        trimRange: null,
    };

    polyline.on("click", (event) => {
        if (selectedLinkId !== link.id) {
            selectLink(link.id);
            return;
        }

        const projection = projectOnPolyline(polyline.getLatLngs(), event.latlng);
        if (!projection) {
            return;
        }

        if (lengthMode.active) {
            return;
        }

        if (!segmentMode.active) {
            return;
        }

        if (!projection) {
            return;
        }

        segmentMode.stateId = state.id;

        if (!segmentMode.startHandle) {
            segmentMode.startHandle = createSegmentHandle(projection, "start", state);
            setInfo("The first three points have been selected. Select the second point or drag this point to the end of the path.");
            return;
        }

        if (!segmentMode.endHandle) {
            segmentMode.endHandle = createSegmentHandle(projection, "end", state);
            renderPendingSegment(state, segmentMode.startHandle.projection, segmentMode.endHandle.projection);
            setInfo("Segment selected. Drag the handles to adjust the segment, then apply it.");
        }
    });

    linkStates.set(link.id, state);
}

async function ensureNetwork() {
    if (network?.links?.length) {
        return network;
    }

    const response = await fetch("/get_network", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bounds),
    });
    network = await response.json();
    localStorage.setItem("selectedNetwork", JSON.stringify(network));
    return network;
}

function collectForcedTrafficLights() {
    return Array.from(forcedTrafficLights);
}

function collectAliases() {
    return Object.fromEntries(
        Array.from(linkStates.values())
            .filter((state) => !state.removed && state.alias)
            .map((state) => [state.id, state.alias])
    );
}

function collectModifications() {
    return Array.from(linkStates.values())
        .filter((state) =>
            state.removed ||
            state.currentLanes !== state.base.lanes ||
            state.segmentEdits.length > 0 ||
            state.turnRestrictions ||
            state.alias ||
            state.trimRange
        )
        .map((state) => ({
            id: state.id,
            alias: state.alias,
            removed: state.removed,
            lanes: state.currentLanes,
            originalLanes: state.base.lanes,
            segmentEdits: state.segmentEdits.map((edit) => ({
                segmentId: edit.segmentId,
                lanes: edit.lanes,
                fromRatio: edit.fromRatio,
                toRatio: edit.toRatio,
                startCoord: edit.startCoord,
                endCoord: edit.endCoord,
            })),
            turnRestrictions: state.turnRestrictions,
            trim: state.trimRange,
        }));
}

function deleteSelectedRoad() {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    const state = getState(selectedLinkId);
    if (!state || state.removed) {
        setInfo("The selected road is already removed.", true);
        return;
    }

    pushHistory();
    state.removed = true;
    state.segmentEdits = [];
    state.turnRestrictions = null;
    state.alias = "";
    state.trimRange = null;

    if (state.polyline && map.hasLayer(state.polyline)) {
        map.removeLayer(state.polyline);
    }
    state.segmentLayers.forEach((layer) => {
        if (map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    state.segmentLayers = [];

    selectedLinkId = null;
    aliasNumberInput.value = "";
    laneInput.value = "1";
    linkTitle.textContent = "No road selected";
    linkMeta.textContent = "Select a blue road.";
    turnContainer.textContent = "Once a route is chosen, this place will fill up.";
    resetSegmentMode();
    resetLengthMode();



    setInfo(`Road ${state.id} removed from this export. It will not be included in generated SUMO files.`);
}
document.getElementById("apply-lanes").addEventListener("click", () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    const laneValue = Number.parseInt(laneInput.value, 10);
    if (!Number.isInteger(laneValue) || laneValue < 1) {
        setInfo("Lane count must be 1 or greater.", true);
        return;
    }

    const state = getState(selectedLinkId);
    pushHistory();
    state.currentLanes = laneValue;
    redrawState(state);
    setInfo("The lane count for the entire road has been updated.");
});

document.getElementById("save-alias").addEventListener("click", () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    const aliasNumber = currentAliasNumber();
    const alias = aliasNumber ? `R${aliasNumber}` : "";

    const selectedState = getState(selectedLinkId);
    const groupStates = getRoadGroupStates(selectedState);

    let targetStates = [selectedState];
    if (groupStates.length > 1) {
        const applyAll = window.confirm(
            "Apply this Road ID to ALL linked segments of this road?\n\nOK = All linked segments\nCancel = Only selected segment"
        );
        targetStates = applyAll ? groupStates : [selectedState];
    }

    pushHistory();
    targetStates.forEach((state) => {
        state.alias = alias;
        redrawState(state);
    });

    selectLink(selectedLinkId);
    setInfo(
        alias
            ? `Road ID saved for ${targetStates.length} segment(s).`
            : "Road ID cleared."
    );
});

document.getElementById("segment-mode").addEventListener("click", async () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    if (!segmentMode.active) {
        segmentMode.active = true;
        segmentMode.stateId = selectedLinkId;
        segmentMode.pendingSelection = null;
        clearSegmentHandles();
        updateSegmentModeButton();
        updateCancelEditButton();
        setInfo("Select two points on the same road. Then drag the endpoints to make precise adjustments.");
        return;
    }

    if (segmentMode.pendingSelection && segmentMode.pendingSelection.stateId === selectedLinkId) {
        const laneValue = Number.parseInt(laneInput.value, 10);
        if (!Number.isInteger(laneValue) || laneValue < 1) {
            setInfo("Lane count must be 1 or greater.", true);
            return;
        }

        const state = getState(selectedLinkId);
        pushHistory();
        state.segmentEdits.push({
            segmentId: `${state.id}-segment-${state.segmentEdits.length + 1}`,
            lanes: laneValue,
            fromRatio: segmentMode.pendingSelection.fromRatio,
            toRatio: segmentMode.pendingSelection.toRatio,
            startCoord: segmentMode.pendingSelection.startCoord,
            endCoord: segmentMode.pendingSelection.endCoord,
            segmentCoords: segmentMode.pendingSelection.segmentCoords,
        });
        redrawState(state);
        resetSegmentMode();
        setInfo("The lane count for the selected segment has been updated.");
        return;
    }

    setInfo("Choose two points on the selected road, then click Save Segment Edit.");
});

document.getElementById("clear-segments").addEventListener("click", () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }
    const state = getState(selectedLinkId);
    pushHistory();
    state.segmentEdits = [];
    redrawState(state);
    resetSegmentMode();
    setInfo("The lane edits for the selected segment have been cleared.");
});
document.getElementById("length-mode").addEventListener("click", async () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    if (!lengthMode.active) {
        resetSegmentMode();
        const state = getState(selectedLinkId);
        const groupStates = getRoadGroupStates(state);
        const geometry = buildGroupGeometry(groupStates);

        if (!geometry.mergedLatLngs || geometry.mergedLatLngs.length < 2 || geometry.totalLength <= 0) {
            setInfo("This road group cannot be length-edited.", true);
            return;
        }

        const windowRange = currentGroupWindow(geometry.ranges, geometry.totalLength);

        lengthMode.active = true;
        lengthMode.stateId = selectedLinkId;
        lengthMode.pendingSelection = null;
        lengthMode.geometry = geometry;
        clearLengthHandles();

        lengthMode.startHandle = createLengthHandle(pointAtRatio(geometry.mergedLatLngs, windowRange.fromRatio), "start", state);
        lengthMode.endHandle = createLengthHandle(pointAtRatio(geometry.mergedLatLngs, windowRange.toRatio), "end", state);
        renderPendingLength(state, lengthMode.startHandle.projection, lengthMode.endHandle.projection);

        updateLengthModeButton();
        updateCancelEditButton();
        setInfo(`Drag the endpoints. This applies to ${groupStates.length} linked road segment(s).`);
        return;
    }

    if (lengthMode.pendingSelection && lengthMode.pendingSelection.stateId === selectedLinkId && lengthMode.geometry) {
        const fromRatio = Math.min(lengthMode.pendingSelection.fromRatio, lengthMode.pendingSelection.toRatio);
        const toRatio = Math.max(lengthMode.pendingSelection.fromRatio, lengthMode.pendingSelection.toRatio);

        if (toRatio - fromRatio < 0.01) {
            setInfo("Selected length is too short. Please leave at least 1% of the road.", true);
            return;
        }

        pushHistory();
        applyGroupTrimFromRatios(lengthMode.geometry.ranges, lengthMode.geometry.totalLength, fromRatio, toRatio);

        const anchorState = getState(selectedLinkId);
        const groupStates = getRoadGroupStates(anchorState);
        groupStates.forEach((item) => redrawState(item));

        resetLengthMode();
        setInfo("Road length saved for linked segments.");
        return;
    }

    resetLengthMode();
    setInfo("Length editing cancelled.");
});

document.getElementById("reset-length").addEventListener("click", () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    const state = getState(selectedLinkId);
    const groupStates = getRoadGroupStates(state);

    pushHistory();
    groupStates.forEach((item) => {
        item.removed = false;
        item.trimRange = null;
        redrawState(item);
    });

    resetLengthMode();
    setInfo("Road length reset for linked segments.");
});

document.getElementById("save-turns").addEventListener("click", () => {
    if (!selectedLinkId) {
        setInfo("Choose a path first.", true);
        return;
    }

    const state = getState(selectedLinkId);
    const outgoing = outgoingTargetsFor(state);
    const allowedTargets = Array.from(turnContainer.querySelectorAll("input[type=checkbox]"))
        .filter((input) => input.checked)
        .map((input) => input.value);

    pushHistory();
    state.turnRestrictions = {
        allowedTargets,
        blockedTargets: outgoing
            .map((item) => item.id)
            .filter((itemId) => !allowedTargets.includes(itemId)),
        allowedAliases: outgoing
            .filter((item) => allowedTargets.includes(item.id))
            .map((item) => displayId(item)),
        blockedAliases: outgoing
    
            .filter((item) => !allowedTargets.includes(item.id))
            .map((item) => displayId(item)),
    };
    setInfo("Turn permissions saved.");
});

console.log("EXPORT JS LOADED");

async function fillRegionAddressFromBounds() {
    if (!bounds || !regionAddressInput) return;
    try {
        const centerLat = (Number(bounds.min_lat) + Number(bounds.max_lat)) / 2;
        const centerLon = (Number(bounds.min_lon) + Number(bounds.max_lon)) / 2;
        const response = await fetch(`/reverse_geocode?lat=${centerLat}&lon=${centerLon}`);
        const payload = await response.json();
        regionAddressInput.value = payload.address || "Address not found";
    } catch (_err) {
        regionAddressInput.value = "Address not found";
    }
}

if (regionNameInput && typeof network !== "undefined" && network && network.cacheKey && !regionNameInput.value && !restoredEditorState) {
    regionNameInput.value = network.cacheKey;
}
fillRegionAddressFromBounds();

async function exportSumoProject() {
    const modifications = collectModifications();
    const hasRoundabout = window.confirm("DÃƒÂ¶nel kavÃ…Å¸ak var mÃ„Â±?\n\nOK = Evet\nCancel = HayÃ„Â±r");

    const response = await fetch("/update_network", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            regionId: currentRegionId ?? null,
            cacheKey: network.cacheKey,
            bounds,
            modifications,
            aliases: collectAliases(),
            networkSummary: { totalLinks: network.links.length },
            forcedTrafficLights: collectForcedTrafficLights(),
            hasRoundabout,
            regionName: regionNameInput ? regionNameInput.value : "",
            regionAddress: regionAddressInput ? regionAddressInput.value : "",
            editorState: captureEditorStatePayload(),
        }),
    });

    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.error || "Export error");
    }
    if (payload.regionId) {
        currentRegionId = Number(payload.regionId);
        const params = new URLSearchParams(window.location.search || "");
        params.set("regionId", String(currentRegionId));
        const nextUrl = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, "", nextUrl);
    }
    if (payload.status === "saved_only") {
        setInfo(payload.warning || "Saved to DB but export failed.", true);
        return payload;
    }

    window.parent.postMessage({
        type: "EXPORT_CREATED",
        data: {
            downloadUrl: payload.downloadUrl,
            exportPath: payload.exportPath,
            sumocfgPath: payload.sumocfgPath,
            summary: payload.summary
        }
    }, "*");

    const link = document.createElement("a");
    link.href = payload.bundleDownloadUrl || payload.downloadUrl;
    const rid = payload.regionId || currentRegionId || "transaction";
    link.download = `transaction_${rid}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    openCameraSetupStage(payload);
    return payload;
}

document.getElementById("export-json").addEventListener("click", async () => {
    console.log("EXPORT CLICKED");
    try {
        const payload = await exportSumoProject();
        if (payload.status === "saved_only") {
            setInfo(payload.warning || "Saved to DB but SUMO export failed.", true);
        } else {
            setInfo("SUMO project files created and downloaded.");
        }
    } catch (error) {
        console.error(error);
        setInfo("Failed to create SUMO project files.", true);
    }
});

if (saveAllBtn) {
    saveAllBtn.addEventListener("click", async () => {
        const ok = window.confirm("Warning: Before saving, double-check all edits and camera setup. Continue?");
        if (!ok) {
            return;
        }
        try {
            const payload = await exportSumoProject();
            exportCameraConfigFile(true);
            if (payload.status === "saved_only") {
                setInfo(payload.warning || "Saved to DB, camera config exported, SUMO export failed.", true);
            } else {
                setInfo("SUMO files and camera config exported.");
            }
        } catch (error) {
            console.error(error);
            setInfo("Failed to save all files.", true);
        }
    });
}

if (saveCameraStageBtn) {
    saveCameraStageBtn.addEventListener("click", async () => {
        try {
            const payload = await exportSumoProject();
            if (payload.status === "saved_only") {
                setInfo(payload.warning || "Camera setup saved to runtime assets, SUMO export failed.", true);
            } else {
                setInfo("Camera setup saved and transaction bundle downloaded.");
            }
        } catch (error) {
            console.error(error);
            setInfo("Failed to save camera setup.", true);
        }
    });
}
document.getElementById("tls-add-start").addEventListener("click", () => {
    addForcedTlsAt("start");
});

document.getElementById("tls-add-end").addEventListener("click", () => {
    addForcedTlsAt("end");
});

document.getElementById("tls-remove-start").addEventListener("click", () => {
    removeForcedTlsAt("start");
});

document.getElementById("tls-remove-end").addEventListener("click", () => {
    removeForcedTlsAt("end");
});

document.getElementById("tls-clear-all").addEventListener("click", () => {
    if (forcedTrafficLights.size === 0) {
        setInfo("No forced traffic lights to clear.", true);
        return;
    }
    pushHistory();
    forcedTrafficLights.clear();
    updateTlsMeta();
    setInfo("All forced traffic-light markers cleared.");
});

if (cancelEditBtn) {
    cancelEditBtn.addEventListener("click", () => {
        if (segmentMode.active) {
            resetSegmentMode();
            setInfo("Segment selection cancelled.");
            return;
        }
        if (lengthMode.active) {
            resetLengthMode();
            setInfo("Length editing cancelled.");
        }
    });
}

if (addCameraBtn) {
    addCameraBtn.addEventListener("click", () => {
        addCamera();
        renderCameraList();
    });
}

if (closeCameraStageBtn) {
    closeCameraStageBtn.addEventListener("click", () => {
        closeCameraSetupStage();
    });
}

if (cameraSourceTypeSelect) {
    cameraSourceTypeSelect.addEventListener("change", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera) {
            return;
        }
        camera.sourceType = cameraSourceTypeSelect.value;
        syncSourceTypeUi();
    });
}

if (cameraNameInput) {
    cameraNameInput.addEventListener("input", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera) {
            return;
        }
        camera.name = cameraNameInput.value || camera.name;
        renderCameraList();
    });
}

if (cameraFileInput) {
    cameraFileInput.addEventListener("change", async () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera || !cameraFileInput.files || cameraFileInput.files.length === 0) {
            return;
        }
        const file = cameraFileInput.files[0];
        // New unsaved system flow: allow immediate local preview before transaction exists.
        if (!currentRegionId) {
            const localUrl = URL.createObjectURL(file);
            camera.sourceType = "file";
            camera.sourceValue = file.name;
            camera.sourcePreviewUrl = localUrl;
            if (cameraPreviewVideo) {
                cameraPreviewVideo.src = localUrl;
                cameraPreviewVideo.style.display = "block";
                cameraPreviewVideo.load();
                cameraPreviewVideo.play().then(() => {
                    setTimeout(() => {
                        const camNow = cameraById(cameraSetup.selectedCameraId);
                        if (camNow) {
                            tryAutoCaptureFrame(camNow);
                        }
                        cameraPreviewVideo.pause();
                    }, 250);
                }).catch(() => {});
            }
            camera.frameDataUrl = "";
            setInfo(`Camera source selected: ${file.name}. Capture frame now. Save later to persist to runtime assets.`);
            return;
        }
        try {
            const fd = new FormData();
            fd.append("file", file);
            const response = await fetch(`/transactions/${encodeURIComponent(currentRegionId)}/camera/upload`, {
                method: "POST",
                body: fd,
            });
            const payload = await response.json();
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || "upload failed");
            }

            camera.sourceType = "file";
            camera.sourceValue = payload.savedPath || file.name;
            camera.sourcePreviewUrl = payload.previewUrl || "";
            if (cameraPreviewVideo) {
                cameraPreviewVideo.src = camera.sourcePreviewUrl;
                cameraPreviewVideo.style.display = "block";
                cameraPreviewVideo.load();
                cameraPreviewVideo.play().then(() => {
                    setTimeout(() => {
                        const camNow = cameraById(cameraSetup.selectedCameraId);
                        if (camNow) {
                            tryAutoCaptureFrame(camNow);
                        }
                        cameraPreviewVideo.pause();
                    }, 250);
                }).catch(() => {});
            }
            camera.frameDataUrl = "";
            setInfo(`Camera source uploaded: ${file.name}. Capturing initial frame...`);
        } catch (error) {
            console.error(error);
            setInfo("Failed to upload camera file.", true);
        }
    });
}

if (loadCameraUrlBtn) {
    loadCameraUrlBtn.addEventListener("click", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera) {
            return;
        }
        const url = (cameraUrlInput?.value || "").trim();
        if (!url) {
            setInfo("Enter a camera stream URL.", true);
            return;
        }
        camera.sourceType = "url";
        camera.sourceValue = url;
        camera.sourcePreviewUrl = url;
        if (cameraPreviewVideo) {
            cameraPreviewVideo.src = url;
            cameraPreviewVideo.style.display = "block";
            cameraPreviewVideo.load();
        }
        camera.frameDataUrl = "";
        setInfo("Camera URL loaded. Capturing initial frame...");
    });
}

if (cameraRoadSelect) {
    cameraRoadSelect.addEventListener("change", () => {
        cameraSetup.selectedRoadForDrawing = cameraRoadSelect.value;
        cameraSetup.draftPoints = [];
        drawOnCameraCanvas();
    });
}

if (linkRoadBtn) {
    linkRoadBtn.addEventListener("click", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera) {
            return;
        }
        const road = cameraRoadSelect?.value;
        if (!road) {
            setInfo("Select a road to link.", true);
            return;
        }
        camera.linkedRoads = [...cameraSetup.availableRoads];
        cameraSetup.selectedRoadForDrawing = road;
        renderLinkedRoads(camera);
        drawOnCameraCanvas();
        setInfo(`${road} linked to ${camera.name}.`);
    });
}

if (captureFrameBtn) {
    captureFrameBtn.addEventListener("click", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera || !cameraPreviewVideo || !cameraPreviewImage) {
            return;
        }
        if (!cameraPreviewVideo.src) {
            setInfo("Load a video footage or stream first.", true);
            return;
        }
        captureFrameForCamera(camera);
    });
}

if (cameraDrawCanvas) {
    cameraDrawCanvas.addEventListener("click", (event) => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera || !cameraPreviewImage || cameraPreviewImage.style.display === "none") {
            setInfo("Frame is not ready yet. Wait for auto capture or use Recapture Frame.", true);
            return;
        }
        const rect = cameraDrawCanvas.getBoundingClientRect();
        const x = Math.round(event.clientX - rect.left);
        const y = Math.round(event.clientY - rect.top);
        cameraSetup.draftPoints.push([x, y]);
        drawOnCameraCanvas();
    });

    cameraDrawCanvas.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        if (cameraSetup.draftPoints.length > 0) {
            cameraSetup.draftPoints.pop();
            drawOnCameraCanvas();
        }
    });
}

if (saveRoadDrawingBtn) {
    saveRoadDrawingBtn.addEventListener("click", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        if (!camera) {
            return;
        }
        const road = cameraSetup.selectedRoadForDrawing;
        if (!road) {
            setInfo("Select a road first.", true);
            return;
        }
        if (cameraSetup.draftPoints.length < 3) {
            setInfo("Draw at least 3 points for a road shape.", true);
            return;
        }
        camera.linkedRoads = [...cameraSetup.availableRoads];
        const savedPoints = cameraSetup.draftPoints.map((pt) => [pt[0], pt[1]]);
        camera.roadDrawings[road] = savedPoints;
        if (!camera.roadDrawingsNormalized) {
            camera.roadDrawingsNormalized = {};
        }
        camera.roadDrawingsNormalized[road] = normalizePoints(
            savedPoints,
            cameraDrawCanvas?.width || 0,
            cameraDrawCanvas?.height || 0
        );
        cameraSetup.draftPoints = [];
        renderLinkedRoads(camera);
        drawOnCameraCanvas();
        setInfo(`${road} drawing saved for ${camera.name}.`);
    });
}

if (clearRoadDrawingBtn) {
    clearRoadDrawingBtn.addEventListener("click", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        const road = cameraSetup.selectedRoadForDrawing;
        if (!camera || !road) {
            return;
        }
        delete camera.roadDrawings[road];
        if (camera.roadDrawingsNormalized) {
            delete camera.roadDrawingsNormalized[road];
        }
        cameraSetup.draftPoints = [];
        drawOnCameraCanvas();
        setInfo(`${road} drawing cleared.`);
    });
}

if (exportCameraConfigBtn) {
    exportCameraConfigBtn.addEventListener("click", () => {
        exportCameraConfigFile();
    });
}

if (openCameraSetupBtn) {
    openCameraSetupBtn.addEventListener("click", () => {
        openCameraSetupStage({
            exportPath: null,
            generatedAt: new Date().toISOString(),
            source: "editor-menu-button",
        });
    });
}

if (cameraPreviewImage) {
    cameraPreviewImage.addEventListener("load", () => {
        fitCanvasToImage();
        drawOnCameraCanvas();
    });
}

if (cameraPreviewVideo) {
    cameraPreviewVideo.addEventListener("loadeddata", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        tryAutoCaptureFrame(camera);
    });
    cameraPreviewVideo.addEventListener("canplay", () => {
        const camera = cameraById(cameraSetup.selectedCameraId);
        tryAutoCaptureFrame(camera);
    });
    cameraPreviewVideo.addEventListener("error", () => {
        const src = cameraPreviewVideo.currentSrc || cameraPreviewVideo.src || "(empty)";
        setInfo(`Video could not be loaded from source: ${src}`, true);
    });
}

document.getElementById("delete-road").addEventListener("click", () => {
    deleteSelectedRoad();
});

aliasPlusBtn.addEventListener("click", () => {
    const next = (currentAliasNumber() || 0) + 1;
    setAliasNumberValue(next);
});

aliasMinusBtn.addEventListener("click", () => {
    const now = currentAliasNumber() || 1;
    setAliasNumberValue(Math.max(1, now - 1));
});

document.getElementById("revert-edit").addEventListener("click", () => {
    undoLastEdit();
});

document.addEventListener("keydown", async (event) => {
    const target = event.target;
    const isTypingContext = target && (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
    );

    if ((event.ctrlKey || event.metaKey) && (event.key === "z" || event.key === "Z")) {
        event.preventDefault();
        undoLastEdit();
        return;
    }

    if (!isTypingContext && (event.key === "Delete" || event.key === "Del")) {
        event.preventDefault();
        deleteSelectedRoad();
        return;
    }

    if (!isTypingContext && (event.key === "Enter")) {
        if (segmentMode.active && segmentMode.pendingSelection && segmentMode.pendingSelection.stateId === selectedLinkId) {
            event.preventDefault();
            document.getElementById("segment-mode").click();
            return;
        }
        if (lengthMode.active && lengthMode.pendingSelection && lengthMode.pendingSelection.stateId === selectedLinkId) {
            event.preventDefault();
            document.getElementById("length-mode").click();
            return;
        }
    }

    if (!isTypingContext && event.key === "Escape") {
        if (segmentMode.active) {
            event.preventDefault();
            resetSegmentMode();
            setInfo("Segment selection cancelled.");
            return;
        }

        if (lengthMode.active) {
            event.preventDefault();
            resetLengthMode();
            setInfo("Length editing cancelled.");
            return;
        }
    }
});

document.getElementById("back-home").addEventListener("click", () => {
    window.location.href = "index.html";
});

(async function init() {
    try {
        const data = await ensureNetwork();
        if (!data.links || data.links.length === 0) {
            throw new Error("Bos yol agi");
        }

        data.links.forEach(attachLink);
        await loadEditorStateIfAvailable();
        const allCoords = data.links.flatMap((link) => link.coords);
        map.fitBounds(allCoords);
        updateTlsMeta();
        updateSegmentModeButton();
        updateLengthModeButton();
        updateCancelEditButton();
        const params = new URLSearchParams(window.location.search || "");
        const shouldOpenCameraSetup = params.get("cameraSetup") === "1";
        if (shouldOpenCameraSetup) {
            openCameraSetupStage({
                exportPath: null,
                generatedAt: new Date().toISOString(),
                source: "menu-camera-setup",
            });
        }
        setInfo(`${data.links.length} routes have been loaded. You can start editing it.`);
    } catch (error) {
        console.error(error);
        setInfo("Network data could not be loaded.", true);
    }
})();

































