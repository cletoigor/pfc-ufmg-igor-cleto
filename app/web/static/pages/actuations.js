// pages/actuations.js — "Actuations": direct control and scene management.
//
// Mirrors figures 4.19 to 4.21: a toggle per device with an optimistic update,
// and a three-step wizard for creating scenes, plus the saved-scene list with
// run and delete.
//
// Every action here runs against the API's dry-run path: it returns the exact
// Tuya payload it would have sent without sending it, which is the point of
// the demo — you can see the command without touching a device.

import { deleteJSON, getJSON, postJSON, state } from "../state.js";
import {
  card,
  clear,
  el,
  emptyState,
  select,
  spinnerRow,
} from "../ui.js";

const WEEKDAYS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

let container = null;

// The wizard's working copy. Kept outside render() so a re-render (caused by a
// filter change elsewhere) does not wipe a half-finished scene.
const draft = {
  step: 1,
  name: "",
  devices: new Set(),
  actions: {},
  time: "",
  days: new Set([0, 1, 2, 3, 4]),
  recurring: true,
  error: null,
};

export function mount(node) {
  container = node;
}

export function render() {
  if (!container) return;
  clear(container);
  container.appendChild(renderToggles());
  container.appendChild(renderWizard());
  const scenesHolder = el("div");
  container.appendChild(scenesHolder);
  renderScenes(scenesHolder);
}

/* ---------------------------------------------------------------- toggles */

function renderToggles() {
  const { wrapper, body } = card("Devices", {
    subtitle: "Turn a device on or off directly.",
  });

  const devices = state.overview?.devices ?? [];
  if (!devices.length) {
    body.appendChild(emptyState("No devices in the registry yet."));
    return wrapper;
  }

  const grid = el("div", "toggle-grid");
  devices.forEach((device) => grid.appendChild(renderToggle(device)));
  body.appendChild(grid);
  return wrapper;
}

function renderToggle(device) {
  const tile = el("div", "toggle-tile");

  const head = el("div", "toggle-head");
  const dot = el(
    "span",
    `state-dot ${device.state === "on" ? "is-on" : device.state === "off" ? "is-off" : "is-unknown"}`
  );
  const name = el("span", "toggle-name", device.name);
  head.append(dot, name);

  const meta = el("span", "toggle-meta", device.last_seen_label ?? "");
  const status = el("span", "toggle-status", "");

  const button = el("button", "toggle-switch");
  button.type = "button";
  let isOn = device.state === "on";
  const paint = () => {
    button.classList.toggle("is-on", isOn);
    button.textContent = isOn ? "On" : "Off";
    button.setAttribute("aria-pressed", String(isOn));
    button.setAttribute("aria-label", `${device.name} is ${isOn ? "on" : "off"}`);
  };
  paint();

  button.addEventListener("click", async () => {
    // Optimistic update: flip immediately so the control feels live, then
    // reconcile against the response and roll back if it failed.
    const previous = isOn;
    isOn = !isOn;
    paint();
    button.disabled = true;
    status.textContent = "simulating…";
    status.className = "toggle-status";

    const { ok, data } = await postJSON(`/api/devices/${encodeURIComponent(device.name)}/toggle`, {
      action: isOn ? "on" : "off",
      dry_run: state.dryRun,
    });
    button.disabled = false;

    if (!ok || !data || data.ok === false) {
      isOn = previous;
      paint();
      status.textContent = data?.error ?? "failed";
      status.className = "toggle-status is-error";
      return;
    }

    const command = data.payload?.commands?.[0];
    status.textContent = `would send ${command?.code} = ${command?.value}`;
    status.className = "toggle-status is-dry";
  });

  tile.append(head, button, meta, status);
  return tile;
}

/* ----------------------------------------------------------------- wizard */

function renderWizard() {
  const { wrapper, body } = card("Create a scene", {
    subtitle: "A named set of actions, run by hand or on a schedule.",
  });

  const steps = el("ol", "wizard-steps");
  ["Name and devices", "Time and actions", "Review"].forEach((label, index) => {
    const step = el("li", `wizard-step ${draft.step === index + 1 ? "is-active" : ""}`);
    step.appendChild(el("span", "wizard-step-number", String(index + 1)));
    step.appendChild(el("span", null, label));
    steps.appendChild(step);
  });
  body.appendChild(steps);

  if (draft.error) {
    body.appendChild(el("p", "form-error", draft.error));
  }

  if (draft.step === 1) body.appendChild(renderStepOne());
  else if (draft.step === 2) body.appendChild(renderStepTwo());
  else body.appendChild(renderStepThree());

  return wrapper;
}

function renderStepOne() {
  const form = el("div", "wizard-body");

  const nameField = el("label", "field");
  nameField.appendChild(el("span", "field-label", "Scene name"));
  const nameInput = el("input", "field-control");
  nameInput.type = "text";
  nameInput.placeholder = "Evening wind-down";
  nameInput.value = draft.name;
  nameInput.addEventListener("input", () => {
    draft.name = nameInput.value;
  });
  nameField.appendChild(nameInput);
  form.appendChild(nameField);

  const devices = (state.overview?.all_devices ?? []);
  const list = el("div", "checkbox-grid");
  devices.forEach((name) => {
    const label = el("label", "checkbox-item");
    const box = el("input");
    box.type = "checkbox";
    box.checked = draft.devices.has(name);
    box.addEventListener("change", () => {
      if (box.checked) {
        draft.devices.add(name);
        if (!draft.actions[name]) draft.actions[name] = "off";
      } else {
        draft.devices.delete(name);
        delete draft.actions[name];
      }
    });
    label.append(box, el("span", null, name));
    list.appendChild(label);
  });
  form.appendChild(el("span", "field-label", "Devices in this scene"));
  form.appendChild(devices.length ? list : emptyState("No devices in the registry."));

  form.appendChild(
    wizardNav({
      next: () => {
        if (!draft.name.trim()) return (draft.error = "Give the scene a name.");
        if (!draft.devices.size) return (draft.error = "Pick at least one device.");
        draft.error = null;
        draft.step = 2;
      },
    })
  );
  return form;
}

function renderStepTwo() {
  const form = el("div", "wizard-body");

  const timeField = el("label", "field");
  timeField.appendChild(el("span", "field-label", "Time (optional)"));
  const timeInput = el("input", "field-control");
  timeInput.type = "time";
  timeInput.value = draft.time;
  timeInput.addEventListener("input", () => {
    draft.time = timeInput.value;
  });
  timeField.appendChild(timeInput);
  form.appendChild(timeField);
  form.appendChild(
    el("p", "field-hint", "Leave the time empty for a scene you only ever run by hand.")
  );

  const days = el("div", "day-picker");
  WEEKDAYS.forEach((day) => {
    const button = el("button", `day-chip ${draft.days.has(day.value) ? "is-on" : ""}`, day.label);
    button.type = "button";
    button.addEventListener("click", () => {
      if (draft.days.has(day.value)) draft.days.delete(day.value);
      else draft.days.add(day.value);
      button.classList.toggle("is-on");
    });
    days.appendChild(button);
  });
  form.appendChild(el("span", "field-label", "Days"));
  form.appendChild(days);

  const recurring = el("label", "checkbox-item");
  const recurringBox = el("input");
  recurringBox.type = "checkbox";
  recurringBox.checked = draft.recurring;
  recurringBox.addEventListener("change", () => {
    draft.recurring = recurringBox.checked;
  });
  recurring.append(recurringBox, el("span", null, "Repeat every week"));
  form.appendChild(recurring);

  form.appendChild(el("span", "field-label", "Action per device"));
  const actions = el("div", "action-list");
  Array.from(draft.devices).forEach((name) => {
    const row = el("div", "action-row");
    row.appendChild(el("span", "action-device", name));
    row.appendChild(
      select(
        [
          { value: "off", label: "Turn off" },
          { value: "on", label: "Turn on" },
        ],
        draft.actions[name] ?? "off",
        (value) => {
          draft.actions[name] = value;
        }
      )
    );
    actions.appendChild(row);
  });
  form.appendChild(actions);

  form.appendChild(
    wizardNav({
      back: () => {
        draft.error = null;
        draft.step = 1;
      },
      next: () => {
        if (draft.time && !draft.days.size) {
          return (draft.error = "A scheduled scene needs at least one day.");
        }
        draft.error = null;
        draft.step = 3;
      },
    })
  );
  return form;
}

function renderStepThree() {
  const form = el("div", "wizard-body");

  const summary = el("dl", "review-list");
  const addRow = (term, value) => {
    summary.appendChild(el("dt", null, term));
    summary.appendChild(el("dd", null, value));
  };
  addRow("Name", draft.name);
  addRow(
    "Actions",
    Array.from(draft.devices)
      .map((name) => `${name} → ${draft.actions[name] === "on" ? "on" : "off"}`)
      .join(", ")
  );
  addRow("Time", draft.time || "run by hand only");
  addRow(
    "Days",
    draft.time
      ? WEEKDAYS.filter((day) => draft.days.has(day.value)).map((day) => day.label).join(", ") || "—"
      : "—"
  );
  addRow("Repeats", draft.time ? (draft.recurring ? "every week" : "once") : "—");
  form.appendChild(summary);

  form.appendChild(
    wizardNav({
      back: () => {
        draft.error = null;
        draft.step = 2;
      },
      saveLabel: "Save scene",
      save: async () => {
        const body = {
          name: draft.name.trim(),
          actions: Object.fromEntries(
            Array.from(draft.devices).map((name) => [name, draft.actions[name] ?? "off"])
          ),
          schedule: {
            time: draft.time || null,
            days_of_week: Array.from(draft.days).sort(),
            recurring: draft.recurring,
          },
        };
        const { ok, data } = await postJSON("/api/scenes", body);
        if (!ok) {
          draft.error = data?.error ?? "Could not save the scene.";
          render();
          return;
        }
        draft.step = 1;
        draft.name = "";
        draft.devices = new Set();
        draft.actions = {};
        draft.time = "";
        draft.error = null;
        render();
      },
    })
  );
  return form;
}

function wizardNav({ back, next, save, saveLabel }) {
  const nav = el("div", "wizard-nav");
  if (back) {
    const button = el("button", "btn btn-ghost", "Back");
    button.type = "button";
    button.addEventListener("click", () => {
      back();
      render();
    });
    nav.appendChild(button);
  }
  if (next) {
    const button = el("button", "btn btn-primary", "Continue");
    button.type = "button";
    button.addEventListener("click", () => {
      next();
      render();
    });
    nav.appendChild(button);
  }
  if (save) {
    const button = el("button", "btn btn-primary", saveLabel ?? "Save");
    button.type = "button";
    button.addEventListener("click", () => save());
    nav.appendChild(button);
  }
  return nav;
}

/* ----------------------------------------------------------------- scenes */

async function renderScenes(holder) {
  clear(holder);
  const { wrapper, body } = card("Saved scenes", {
    subtitle: "Expand a scene to see its actions, run it now, or delete it.",
  });
  holder.appendChild(wrapper);
  body.appendChild(spinnerRow("Loading scenes…"));

  const { ok, data } = await getJSON("/api/scenes");
  clear(body);

  if (!ok || !data) {
    body.appendChild(emptyState("Could not load scenes."));
    return;
  }
  const scenes = data.scenes ?? [];
  if (!scenes.length) {
    body.appendChild(emptyState("No scenes yet.", "Create one above."));
    return;
  }

  scenes.forEach((scene) => body.appendChild(renderScene(scene, holder)));
}

function renderScene(scene, holder) {
  const details = el("details", "scene");
  const summary = el("summary", "scene-summary");
  summary.appendChild(el("span", "scene-name", scene.name));
  summary.appendChild(
    el(
      "span",
      "scene-schedule",
      scene.schedule?.time
        ? `${scene.schedule.time} · ${describeDays(scene.schedule.days_of_week)}` +
            (scene.schedule.recurring ? "" : " · once")
        : "manual only"
    )
  );
  details.appendChild(summary);

  const body = el("div", "scene-body");

  const actions = el("ul", "scene-actions");
  Object.entries(scene.actions ?? {}).forEach(([device, action]) => {
    const item = el("li");
    item.appendChild(el("span", "scene-action-device", device));
    item.appendChild(el("span", `scene-action-verb is-${action}`, action === "on" ? "turn on" : "turn off"));
    actions.appendChild(item);
  });
  body.appendChild(actions);

  if (scene.last_executed_at) {
    body.appendChild(el("p", "scene-meta", `Last run ${scene.last_executed_at.replace("T", " ")}`));
  }

  const result = el("div", "scene-result");
  const buttons = el("div", "scene-buttons");

  const runButton = el("button", "btn btn-primary", "Run now");
  runButton.type = "button";
  runButton.addEventListener("click", async () => {
    runButton.disabled = true;
    clear(result).appendChild(spinnerRow("Running…"));
    const { ok, data } = await postJSON(`/api/scenes/${scene.id}/run`, { dry_run: state.dryRun });
    runButton.disabled = false;
    clear(result);
    if (!ok || !data) {
      result.appendChild(el("p", "form-error", "Could not run the scene."));
      return;
    }
    const list = el("ul", "scene-run-results");
    (data.results ?? []).forEach((entry) => {
      const command = entry.payload?.commands?.[0];
      const item = el("li", entry.ok ? "is-ok" : "is-error");
      item.textContent = entry.error
        ? `${entry.device}: ${entry.error}`
        : `${entry.device}: would send ${command?.code} = ${command?.value}`;
      list.appendChild(item);
    });
    result.appendChild(list);
  });

  // Deleting is destructive and cheap to misclick, so it asks first — inline,
  // not through a browser dialog, which would block the whole page.
  const deleteButton = el("button", "btn btn-danger", "Delete");
  deleteButton.type = "button";
  deleteButton.addEventListener("click", () => {
    clear(result);
    const confirmRow = el("div", "confirm-row");
    confirmRow.appendChild(el("span", null, `Delete “${scene.name}”?`));
    const yes = el("button", "btn btn-danger", "Delete");
    yes.type = "button";
    yes.addEventListener("click", async () => {
      await deleteJSON(`/api/scenes/${scene.id}`);
      renderScenes(holder);
    });
    const no = el("button", "btn btn-ghost", "Cancel");
    no.type = "button";
    no.addEventListener("click", () => clear(result));
    confirmRow.append(yes, no);
    result.appendChild(confirmRow);
  });

  buttons.append(runButton, deleteButton);
  body.append(buttons, result);
  details.appendChild(body);
  return details;
}

function describeDays(days) {
  if (!days || !days.length) return "any day";
  if (days.length === 7) return "every day";
  const names = WEEKDAYS.filter((day) => days.includes(day.value)).map((day) => day.label);
  if (names.length === 5 && !days.includes(5) && !days.includes(6)) return "weekdays";
  return names.join(", ");
}
