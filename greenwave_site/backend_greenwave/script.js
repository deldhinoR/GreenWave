const map = L.map("map").setView([39.92, 32.85], 13);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
}).addTo(map);

const previewGroup = L.layerGroup().addTo(map);
const drawnItems = new L.FeatureGroup().addTo(map);
const simulateBtn = document.getElementById("simulate-btn");
const cancelBtn = document.getElementById("cancel-btn");
const statusEl = document.getElementById("status");

let selectedBounds = null;
let selectedNetwork = null;

simulateBtn.disabled = true;
cancelBtn.disabled = true;

const drawControl = new L.Control.Draw({
    draw: {
        polyline: false,
        polygon: false,
        circle: false,
        circlemarker: false,
        marker: false,
        rectangle: true,
    },
    edit: {
        featureGroup: drawnItems,
        edit: false,
        remove: true,
    },
});

map.addControl(drawControl);

function setStatus(message, isError = false) {
    statusEl.textContent = message;
    statusEl.dataset.error = isError ? "true" : "false";
}

function clearPreviousSelection() {
    drawnItems.clearLayers();
    previewGroup.clearLayers();
    selectedBounds = null;
    selectedNetwork = null;
    simulateBtn.disabled = true;
    cancelBtn.disabled = true;
}

function drawPreview(links) {
    previewGroup.clearLayers();

    links.forEach((link) => {
        L.polyline(link.coords, {
            color: "#d62828",
            weight: 3,
            opacity: 0.9,
        })
            .bindTooltip(`${link.name || "Road"} | lanes: ${link.lanes}`, {
                sticky: true,
            })
            .addTo(previewGroup);
    });
}

async function loadBoundsAndPreview(bounds, fit = true) {
    selectedBounds = bounds;
    setStatus("Roads are being built...");
    cancelBtn.disabled = false;

    try {
        const response = await fetch("http://127.0.0.1:5000/get_network", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(selectedBounds),
        });
        const network = await response.json();

        if (!network.links || network.links.length === 0) {
            setStatus("No roads found in the selected area.", true);
            return;
        }

        selectedNetwork = network;
        drawPreview(network.links);
        const rect = L.rectangle(
            [
                [selectedBounds.min_lat, selectedBounds.min_lon],
                [selectedBounds.max_lat, selectedBounds.max_lon],
            ],
            { color: "#2563eb", weight: 2, fillOpacity: 0.05 }
        );
        drawnItems.clearLayers();
        drawnItems.addLayer(rect);
        if (fit) {
            map.fitBounds(rect.getBounds());
        }
        simulateBtn.disabled = false;
        setStatus(`${network.links.length} routes have been loaded. You can start editing it.`);
    } catch (error) {
        console.error(error);
        setStatus("An error occurred while fetching road data.", true);
    }
}

map.on(L.Draw.Event.CREATED, async (event) => {
    clearPreviousSelection();

    const layer = event.layer;
    drawnItems.addLayer(layer);

    const bounds = layer.getBounds();
    selectedBounds = {
        min_lat: bounds.getSouthWest().lat,
        min_lon: bounds.getSouthWest().lng,
        max_lat: bounds.getNorthEast().lat,
        max_lon: bounds.getNorthEast().lng,
    };

    await loadBoundsAndPreview(selectedBounds, true);
});

map.on(L.Draw.Event.DELETED, () => {
    clearPreviousSelection();
    setStatus("Selection deleted. Please select the area you wish to edit.");
});

cancelBtn.addEventListener("click", () => {
    clearPreviousSelection();
    setStatus("Selection canceled. Please select the area you wish to edit.");
});

simulateBtn.addEventListener("click", () => {
    if (!selectedBounds || !selectedNetwork) {
        return;
    }

    localStorage.setItem("selectedBounds", JSON.stringify(selectedBounds));
    localStorage.setItem("selectedNetwork", JSON.stringify(selectedNetwork));
    window.location.href = "netedit.html";
});

(async function autoLoadFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const min_lat = Number(params.get("min_lat"));
    const min_lon = Number(params.get("min_lon"));
    const max_lat = Number(params.get("max_lat"));
    const max_lon = Number(params.get("max_lon"));
    if ([min_lat, min_lon, max_lat, max_lon].some((v) => Number.isNaN(v))) {
        return;
    }
    clearPreviousSelection();
    await loadBoundsAndPreview({ min_lat, min_lon, max_lat, max_lon }, true);
    const regionName = params.get("regionName");
    if (regionName) {
        setStatus(`Loaded ${regionName}. Review then click Edit.`);
    }
})();
