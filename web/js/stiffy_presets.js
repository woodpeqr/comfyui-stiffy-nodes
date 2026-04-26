import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const SIMPLE_NODE_TYPE = "StiffySimplePresetNode";
const COMPLEX_NODE_TYPE = "StiffyComplexPresetNode";
const NEW_PRESET_SENTINEL = "-- new --";

// ─── API helpers ─────────────────────────────────────────────────────────────

async function fetchPreset(name) {
    const resp = await api.fetchApi(`/api/stiffy/presets/${encodeURIComponent(name)}`);
    if (!resp.ok) return null;
    return await resp.json();
}

async function fetchPresetNames(category) {
    const url = category
        ? `/api/stiffy/presets?category=${encodeURIComponent(category)}`
        : "/api/stiffy/presets";
    const resp = await api.fetchApi(url);
    if (!resp.ok) return [];
    return await resp.json();
}

// ─── Widget helpers ──────────────────────────────────────────────────────────

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
    const w = getWidget(node, name);
    if (w) w.value = value;
}

// ─── Simple preset node ──────────────────────────────────────────────────────

function setupSimplePresetNode(node) {
    const loadPresetWidget = getWidget(node, "load_preset");
    if (!loadPresetWidget) return;

    const orig = loadPresetWidget.callback;
    loadPresetWidget.callback = async function (value) {
        if (orig) orig.call(this, value);
        if (!value || value === NEW_PRESET_SENTINEL) return;

        const entries = await fetchPreset(value);
        if (!entries) return;

        const catEntry = entries.find((e) => e.category !== "negative");
        const negEntry = entries.find((e) => e.category === "negative");

        setWidgetValue(node, "preset_name", value);
        setWidgetValue(node, "prompt", catEntry ? catEntry.prompt : "");
        setWidgetValue(node, "negative_prompt", negEntry ? negEntry.prompt : "");

        node.graph?.setDirtyCanvas(true);
    };
}

// ─── Complex preset node ─────────────────────────────────────────────────────

function setupComplexPresetNode(node) {
    const loadPresetWidget = getWidget(node, "load_preset");
    if (!loadPresetWidget) return;

    const orig = loadPresetWidget.callback;
    loadPresetWidget.callback = async function (value) {
        if (orig) orig.call(this, value);
        if (!value || value === NEW_PRESET_SENTINEL) return;

        const entries = await fetchPreset(value);
        if (!entries) return;

        setWidgetValue(node, "preset_name", value);

        // Clear all category fields first, then populate from preset
        for (const w of node.widgets ?? []) {
            if (w.name.endsWith("_prompt") && w.name !== "negative_prompt") {
                w.value = "";
            }
        }
        setWidgetValue(node, "negative_prompt", "");

        for (const entry of entries) {
            if (entry.category === "negative") {
                setWidgetValue(node, "negative_prompt", entry.prompt);
            } else {
                setWidgetValue(node, `${entry.category}_prompt`, entry.prompt);
            }
        }

        node.graph?.setDirtyCanvas(true);
    };
}

// ─── Extension ───────────────────────────────────────────────────────────────

app.registerExtension({
    name: "stiffy.presets",

    async nodeCreated(node) {
        if (node.type === SIMPLE_NODE_TYPE) {
            setupSimplePresetNode(node);
        } else if (node.type === COMPLEX_NODE_TYPE) {
            setupComplexPresetNode(node);
        }
    },
});
