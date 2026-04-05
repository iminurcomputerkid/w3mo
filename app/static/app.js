const state = {
  devices: [],
  busy: false,
  pollHandle: null,
};

const pollSeconds = Number(document.body.dataset.pollSeconds || 20);
const alertsEl = document.getElementById("alerts");
const devicesGridEl = document.getElementById("devices-grid");
const panelStatusEl = document.getElementById("panel-status");
const totalDevicesEl = document.getElementById("total-devices");
const reachableDevicesEl = document.getElementById("reachable-devices");
const lastDiscoveryEl = document.getElementById("last-discovery");
const discoverButton = document.getElementById("discover-button");
const refreshButton = document.getElementById("refresh-button");
const manualForm = document.getElementById("manual-device-form");
const manualInput = document.getElementById("manual-device-input");
const manualSubmitButton = document.getElementById("manual-device-submit");
const manualAddressesEl = document.getElementById("manual-addresses");
const scheduleForm = document.getElementById("schedule-form");
const scheduleEditIdInput = document.getElementById("schedule-edit-id");
const scheduleNameInput = document.getElementById("schedule-name");
const scheduleDeviceSelect = document.getElementById("schedule-device");
const scheduleTypeSelect = document.getElementById("schedule-type");
const scheduleActionSelect = document.getElementById("schedule-action");
const scheduleTimeInput = document.getElementById("schedule-time");
const scheduleDurationInput = document.getElementById("schedule-duration");
const scheduleWeekdaysWrap = document.getElementById("schedule-weekdays-wrap");
const scheduleBrightnessWrap = document.getElementById("schedule-brightness-wrap");
const scheduleBrightnessInput = document.getElementById("schedule-brightness");
const scheduleBrightnessValue = document.getElementById("schedule-brightness-value");
const scheduleSubmitButton = document.getElementById("schedule-submit");
const scheduleCancelEditButton = document.getElementById("schedule-cancel-edit");
const schedulesListEl = document.getElementById("schedules-list");
const scheduleTimelineEl = document.getElementById("schedule-timeline");
const scheduleWeekdayInputs = [...document.querySelectorAll(".schedule-weekday")];
const template = document.getElementById("device-card-template");
let scheduleClockHandle = null;

function showAlerts(messages = [], tone = "warning") {
  alertsEl.innerHTML = "";
  messages.filter(Boolean).forEach((message) => {
    const alert = document.createElement("div");
    alert.className = `alert ${tone}`;
    alert.textContent = message;
    alertsEl.appendChild(alert);
  });
}

function addAlert(message, tone = "success") {
  showAlerts([message], tone);
}

function renderManualAddresses(addresses = []) {
  manualAddressesEl.innerHTML = "";
  if (!addresses.length) {
    const empty = document.createElement("p");
    empty.className = "device-status";
    empty.textContent = "No manual device addresses saved.";
    manualAddressesEl.appendChild(empty);
    return;
  }
  addresses.forEach((address) => {
    const chip = document.createElement("div");
    chip.className = "manual-chip";

    const label = document.createElement("span");
    label.textContent = address;

    const remove = document.createElement("button");
    remove.className = "button button-ghost manual-chip-remove";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => removeManualAddress(address, remove));

    chip.append(label, remove);
    manualAddressesEl.appendChild(chip);
  });
}

function populateScheduleDeviceOptions() {
  const currentValue = scheduleDeviceSelect.value;
  scheduleDeviceSelect.innerHTML = "";
  if (!state.devices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Discover a device first";
    scheduleDeviceSelect.appendChild(option);
    return;
  }
  state.devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.id;
    option.textContent = `${device.name} (${device.type})`;
    option.dataset.brightnessSupported = String(device.brightness_supported);
    scheduleDeviceSelect.appendChild(option);
  });
  if ([...scheduleDeviceSelect.options].some((item) => item.value === currentValue)) {
    scheduleDeviceSelect.value = currentValue;
  }
}

function resetScheduleForm() {
  scheduleForm.reset();
  scheduleEditIdInput.value = "";
  scheduleSubmitButton.textContent = "Save Schedule";
  scheduleSubmitButton.dataset.defaultLabel = "Save Schedule";
  scheduleCancelEditButton.hidden = true;
  resetWeekdays();
  scheduleBrightnessInput.value = "60";
  scheduleBrightnessValue.textContent = "60%";
  syncScheduleEditorForDeviceChange();
}

function updateScheduleActionOptions() {
  const selectedOption = scheduleDeviceSelect.selectedOptions[0];
  const brightnessSupported =
    selectedOption?.dataset.brightnessSupported === "true";
  const currentAction = scheduleActionSelect.value;
  [...scheduleActionSelect.options].forEach((option) => {
    if (option.value === "brightness") {
      option.hidden = !brightnessSupported;
      option.disabled = !brightnessSupported;
    }
  });
  if (!brightnessSupported && currentAction === "brightness") {
    scheduleActionSelect.value = "on";
  }
}

function syncScheduleEditorForDeviceChange() {
  updateScheduleActionOptions();
  refreshScheduleFormVisibility();
}

function describeSchedule(schedule) {
  if (schedule.schedule_type === "countdown") {
    if (schedule.action === "off") {
      return `Timer for ${schedule.device_name || "device"} will turn off after ${schedule.duration_minutes} minute(s).`;
    }
    return `Timer for ${schedule.device_name || "device"} running now for ${schedule.duration_minutes} minute(s).`;
  }
  const weekdayLabel = (schedule.weekdays || []).join(", ");
  const base = `${schedule.device_name || "Device"} daily at ${schedule.time_of_day} on ${weekdayLabel}`;
  if (schedule.action === "brightness") {
    return `${base}, set brightness to ${schedule.brightness}%`;
  }
  if (schedule.duration_minutes && schedule.action === "on") {
    return `${base}, turn on for ${schedule.duration_minutes} minute(s)`;
  }
  return `${base}, turn ${schedule.action}`;
}

function renderTimeline(events = []) {
  scheduleTimelineEl.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "device-status";
    empty.textContent = "No scheduled events in the next 24 hours.";
    scheduleTimelineEl.appendChild(empty);
    return;
  }
  events.forEach((event) => {
    const row = document.createElement("article");
    row.className = "timeline-item";
    const title = document.createElement("strong");
    const actionText =
      event.action === "brightness" && event.brightness !== null
        ? `Set brightness to ${event.brightness}%`
        : `Turn ${event.action}`;
    title.textContent = `${formatDate(event.event_time)}: ${event.schedule_name}`;
    const meta = document.createElement("p");
    meta.textContent =
      event.event_type === "auto_off"
        ? `${event.device_name || "Device"} automatic off`
        : `${event.device_name || "Device"}: ${actionText}`;
    row.append(title, meta);
    scheduleTimelineEl.appendChild(row);
  });
}

function formatDurationRemaining(targetIso) {
  if (!targetIso) {
    return null;
  }
  const diffMs = new Date(targetIso).getTime() - Date.now();
  if (diffMs <= 0) {
    return "less than a minute remaining";
  }
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts = [];
  if (hours) {
    parts.push(`${hours}h`);
  }
  if (minutes || hours) {
    parts.push(`${minutes}m`);
  }
  parts.push(`${seconds}s`);
  return `${parts.join(" ")} remaining`;
}

function selectedWeekdays() {
  return scheduleWeekdayInputs
    .filter((input) => input.checked)
    .map((input) => input.value);
}

function resetWeekdays() {
  scheduleWeekdayInputs.forEach((input) => {
    input.checked = true;
  });
}

function renderSchedules(schedules = []) {
  schedulesListEl.innerHTML = "";
  if (!schedules.length) {
    const empty = document.createElement("p");
    empty.className = "device-status";
    empty.textContent = "No schedules configured.";
    schedulesListEl.appendChild(empty);
    return;
  }
  schedules.forEach((schedule) => {
    const card = document.createElement("article");
    card.className = `schedule-card ${schedule.schedule_type === "countdown" ? "is-timer" : "is-daily"}`;

    const header = document.createElement("div");
    header.className = "schedule-card-header";
    const titleWrap = document.createElement("div");
    const deviceLabel = document.createElement("div");
    deviceLabel.className = "schedule-device-label";
    deviceLabel.textContent = schedule.device_name || "Unknown device";
    const title = document.createElement("h3");
    title.textContent = schedule.name;
    titleWrap.append(deviceLabel, title);
    const statePill = document.createElement("span");
    statePill.className = `state-pill ${schedule.enabled ? "on" : "off"}`;
    statePill.textContent = schedule.enabled ? "ENABLED" : "DISABLED";
    header.append(titleWrap, statePill);

    const desc = document.createElement("p");
    desc.textContent = describeSchedule(schedule);

    const meta = document.createElement("p");
    meta.className = "schedule-meta";
    const parts = [];
    if (schedule.schedule_type === "daily" && schedule.next_run_at) {
      parts.push(`Next run ${formatDate(schedule.next_run_at)}`);
    }
    if (schedule.pending_off_at) {
      parts.push(`Auto-off ${formatDate(schedule.pending_off_at)}`);
    }
    if (schedule.schedule_type === "countdown" && schedule.pending_off_at) {
      const remaining = formatDurationRemaining(schedule.pending_off_at);
      if (remaining) {
        parts.push(remaining);
      }
    }
    if (schedule.last_run_at && schedule.schedule_type === "countdown") {
      parts.push(`Started ${formatDate(schedule.last_run_at)}`);
    }
    if (schedule.last_error) {
      parts.push(`Last error: ${schedule.last_error}`);
    }
    meta.textContent = parts.join(" • ");

    const actions = document.createElement("div");
    actions.className = "schedule-card-actions";
    const leftActions = document.createElement("div");
    leftActions.className = "schedule-inline-actions";

    if (schedule.schedule_type === "daily") {
      const edit = document.createElement("button");
      edit.className = "button button-secondary button-small";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => beginEditSchedule(schedule));
      leftActions.append(edit);
    }

    if (schedule.schedule_type === "countdown" && schedule.enabled) {
      const plus15 = document.createElement("button");
      plus15.className = "button button-secondary button-small";
      plus15.textContent = "+15 min";
      plus15.addEventListener("click", () =>
        adjustTimer(schedule.id, 15, plus15),
      );
      const minus15 = document.createElement("button");
      minus15.className = "button button-secondary button-small";
      minus15.textContent = "-15 min";
      minus15.addEventListener("click", () =>
        adjustTimer(schedule.id, -15, minus15),
      );
      leftActions.append(plus15, minus15);
    }

    const rightActions = document.createElement("div");
    rightActions.className = "schedule-inline-actions";

    const toggle = document.createElement("button");
    toggle.className = "button button-secondary button-small";
    toggle.textContent = schedule.enabled ? "Disable" : "Enable";
    toggle.addEventListener("click", () =>
      toggleSchedule(schedule.id, !schedule.enabled, toggle),
    );
    const remove = document.createElement("button");
    remove.className = "button button-ghost button-small";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => deleteSchedule(schedule.id, remove));
    rightActions.append(toggle, remove);
    actions.append(leftActions, rightActions);

    card.append(header, desc, meta, actions);
    schedulesListEl.appendChild(card);
  });
}

function beginEditSchedule(schedule) {
  if (schedule.schedule_type !== "daily") {
    return;
  }
  scheduleEditIdInput.value = schedule.id;
  scheduleNameInput.value = schedule.name || "";
  scheduleDeviceSelect.value = schedule.device_id;
  scheduleTypeSelect.value = "daily";
  scheduleActionSelect.value = schedule.action;
  scheduleTimeInput.value = schedule.time_of_day || "";
  scheduleDurationInput.value = schedule.duration_minutes || "";
  scheduleWeekdayInputs.forEach((input) => {
    input.checked = (schedule.weekdays || []).includes(input.value);
  });
  if (schedule.action === "brightness" && schedule.brightness !== null) {
    scheduleBrightnessInput.value = String(schedule.brightness);
    scheduleBrightnessValue.textContent = `${schedule.brightness}%`;
  }
  scheduleSubmitButton.textContent = "Update Schedule";
  scheduleSubmitButton.dataset.defaultLabel = "Update Schedule";
  scheduleCancelEditButton.hidden = false;
  syncScheduleEditorForDeviceChange();
  scheduleForm.scrollIntoView({ behavior: "smooth", block: "center" });
}

function refreshScheduleFormVisibility() {
  const scheduleType = scheduleTypeSelect.value;
  updateScheduleActionOptions();
  const action = scheduleActionSelect.value;
  const selectedOption = scheduleDeviceSelect.selectedOptions[0];
  const brightnessSupported =
    selectedOption?.dataset.brightnessSupported === "true";

  scheduleTimeInput.disabled = scheduleType !== "daily";
  scheduleTimeInput.hidden = scheduleType !== "daily";
  scheduleWeekdaysWrap.hidden = scheduleType !== "daily";

  if (scheduleType === "countdown") {
    scheduleDurationInput.placeholder = "Run for minutes";
  } else {
    scheduleDurationInput.placeholder = "Optional auto-off minutes";
  }

  if (action === "off") {
    scheduleDurationInput.disabled = scheduleType === "daily";
  } else {
    scheduleDurationInput.disabled = false;
  }

  scheduleBrightnessWrap.hidden = !(action === "brightness" && brightnessSupported);
}

function setBusy(element, busy, labelWhenBusy) {
  if (!element) {
    return;
  }
  if (!element.dataset.defaultLabel) {
    element.dataset.defaultLabel = element.textContent;
  }
  element.disabled = busy;
  element.textContent = busy ? labelWhenBusy : element.dataset.defaultLabel;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed.");
  }
  return payload;
}

function formatDate(value) {
  if (!value) {
    return "Never";
  }
  return new Date(value).toLocaleString();
}

function buildMetaEntries(device) {
  const entries = [
    ["IP", device.host || "Unknown"],
    ["Port", String(device.port || "")],
    ["Discovery", device.discovery_method],
    ["Model", device.model_name || device.model || "Unknown"],
  ];

  if (device.brightness !== null && device.brightness !== undefined) {
    entries.push(["Brightness", `${device.brightness}%`]);
  }
  if (device.firmware_version) {
    entries.push(["Firmware", device.firmware_version]);
  }
  if (device.mac) {
    entries.push(["MAC", device.mac]);
  }
  if (device.serial_number) {
    entries.push(["Serial", device.serial_number]);
  }
  if (device.insight?.current_power_watts !== null && device.insight?.current_power_watts !== undefined) {
    entries.push(["Power", `${device.insight.current_power_watts} W`]);
    entries.push(["Today", `${device.insight.today_kwh} kWh`]);
    entries.push(["Standby", device.insight.standby_state || "unknown"]);
  }
  return entries;
}

function getBrightnessValue(device) {
  if (device.brightness !== null && device.brightness !== undefined) {
    return device.brightness;
  }
  if (device.state === "on") {
    return 100;
  }
  return 0;
}

function renderDevices(payload) {
  state.devices = payload.devices || [];
  totalDevicesEl.textContent = String(payload.total_devices || 0);
  reachableDevicesEl.textContent = String(payload.reachable_devices || 0);
  lastDiscoveryEl.textContent = formatDate(payload.latest_discovery);

  const alerts = [];
  if (payload.partial_discovery) {
    alerts.push("Discovery completed with warnings. Some devices may be stale or unreachable.");
  }
  (payload.issues || []).forEach((issue) => alerts.push(issue));
  showAlerts(alerts, payload.issues?.length ? "warning" : "warning");

  devicesGridEl.innerHTML = "";
  if (!state.devices.length) {
    panelStatusEl.textContent = "No compatible WeMo switches found yet.";
    populateScheduleDeviceOptions();
    syncScheduleEditorForDeviceChange();
    return;
  }

  panelStatusEl.textContent = `${state.devices.length} devices loaded`;
  populateScheduleDeviceOptions();
  syncScheduleEditorForDeviceChange();

  state.devices.forEach((device) => {
    const node = template.content.firstElementChild.cloneNode(true);
    const nameEl = node.querySelector(".device-name");
    const typeEl = node.querySelector(".device-type");
    const stateEl = node.querySelector(".state-pill");
    const statusEl = node.querySelector(".device-status");
    const metaEl = node.querySelector(".meta-grid");
    const brightnessControlEl = node.querySelector(".brightness-control");
    const brightnessValueEl = node.querySelector(".brightness-value");
    const brightnessSliderEl = node.querySelector(".brightness-slider");
    const brightnessApplyButton = node.querySelector(".action-brightness-apply");
    const onButton = node.querySelector(".action-on");
    const offButton = node.querySelector(".action-off");
    const refreshButton = node.querySelector(".action-refresh");

    nameEl.textContent = device.name;
    typeEl.textContent = device.type;
    stateEl.textContent = device.state.toUpperCase();
    stateEl.classList.add(device.state);

    const statusBits = [device.status_message];
    if (device.last_error) {
      statusBits.push(`Last error: ${device.last_error}`);
    }
    if (device.last_refreshed) {
      statusBits.push(`Updated ${formatDate(device.last_refreshed)}`);
    }
    statusEl.textContent = statusBits.filter(Boolean).join(" • ");

    buildMetaEntries(device).forEach(([label, value]) => {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      metaEl.append(dt, dd);
    });

    onButton.disabled = device.state === "on" && device.reachable;
    offButton.disabled = device.state === "off" && device.reachable;

    if (device.brightness_supported) {
      brightnessControlEl.hidden = false;
      const initialBrightness = getBrightnessValue(device);
      brightnessSliderEl.value = String(initialBrightness);
      brightnessValueEl.textContent = `${initialBrightness}%`;
      brightnessSliderEl.disabled = !device.reachable;
      brightnessApplyButton.disabled = !device.reachable;

      brightnessSliderEl.addEventListener("input", () => {
        brightnessValueEl.textContent = `${brightnessSliderEl.value}%`;
      });
      brightnessApplyButton.addEventListener("click", () => {
        const brightness = Number(brightnessSliderEl.value);
        handleBrightnessChange(device.id, brightness, brightnessApplyButton);
      });
    }

    onButton.addEventListener("click", () => handleDeviceAction(device.id, "on", onButton));
    offButton.addEventListener("click", () => handleDeviceAction(device.id, "off", offButton));
    refreshButton.addEventListener("click", () => handleDeviceAction(device.id, "refresh", refreshButton));

    devicesGridEl.appendChild(node);
  });
}

async function loadDevices({ refresh = false } = {}) {
  const payload = await api(`/api/devices?refresh=${refresh ? "true" : "false"}`);
  renderDevices(payload);
}

async function loadManualAddresses() {
  const payload = await api("/api/manual-addresses");
  renderManualAddresses(payload.addresses || []);
}

async function loadSchedules() {
  const payload = await api("/api/schedules");
  renderSchedules(payload.schedules || []);
  renderTimeline(payload.upcoming_events || []);
}

function startScheduleCountdowns() {
  if (scheduleClockHandle) {
    window.clearInterval(scheduleClockHandle);
  }
  scheduleClockHandle = window.setInterval(() => {
    loadSchedules().catch(() => {});
  }, 1000);
}

async function discoverDevices() {
  setBusy(discoverButton, true, "Scanning...");
  panelStatusEl.textContent = "Searching the LAN for WeMo switches...";
  try {
    const payload = await api("/api/discover", { method: "POST" });
    renderDevices(payload);
    addAlert("Discovery finished.", payload.issues?.length ? "warning" : "success");
  } catch (error) {
    showAlerts([error.message], "error");
    panelStatusEl.textContent = "Discovery failed.";
  } finally {
    setBusy(discoverButton, false, "Scanning...");
  }
}

async function addManualAddress(event) {
  event.preventDefault();
  const address = manualInput.value.trim();
  if (!address) {
    showAlerts(["Enter an IP address or hostname first."], "error");
    return;
  }
  setBusy(manualSubmitButton, true, "Adding...");
  try {
    const payload = await api("/api/manual-addresses", {
      method: "POST",
      body: JSON.stringify({ address }),
    });
    renderManualAddresses(payload.addresses || []);
    manualInput.value = "";
    addAlert(`Saved manual address ${address}.`, "success");
    await discoverDevices();
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(manualSubmitButton, false, "Adding...");
  }
}

async function removeManualAddress(address, button) {
  setBusy(button, true, "Removing...");
  try {
    const payload = await api(
      `/api/manual-addresses?address=${encodeURIComponent(address)}`,
      { method: "DELETE" },
    );
    renderManualAddresses(payload.addresses || []);
    addAlert(`Removed manual address ${address}.`, "success");
    await discoverDevices();
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, "Removing...");
  }
}

async function createSchedule(event) {
  event.preventDefault();
  const editId = scheduleEditIdInput.value || null;
  const payload = {
    name: scheduleNameInput.value.trim(),
    device_id: scheduleDeviceSelect.value,
    schedule_type: editId ? "daily" : scheduleTypeSelect.value,
    action: scheduleActionSelect.value,
    brightness:
      scheduleActionSelect.value === "brightness"
        ? Number(scheduleBrightnessInput.value)
        : null,
    time_of_day: scheduleTypeSelect.value === "daily" ? scheduleTimeInput.value : null,
    duration_minutes: scheduleDurationInput.value
      ? Number(scheduleDurationInput.value)
      : null,
    weekdays: scheduleTypeSelect.value === "daily" ? selectedWeekdays() : [],
  };

  setBusy(scheduleSubmitButton, true, "Saving...");
  try {
    const response = await api(editId ? `/api/schedules/${encodeURIComponent(editId)}` : "/api/schedules", {
      method: editId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    renderSchedules(response.schedules || []);
    renderTimeline(response.upcoming_events || []);
    resetScheduleForm();
    addAlert(editId ? "Schedule updated." : "Schedule saved.", "success");
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(scheduleSubmitButton, false, "Saving...");
  }
}

async function adjustTimer(scheduleId, deltaMinutes, button) {
  setBusy(button, true, deltaMinutes > 0 ? "Extending..." : "Updating...");
  try {
    const response = await api(
      `/api/schedules/${encodeURIComponent(scheduleId)}/adjust-timer`,
      {
        method: "POST",
        body: JSON.stringify({ delta_minutes: deltaMinutes }),
      },
    );
    renderSchedules(response.schedules || []);
    renderTimeline(response.upcoming_events || []);
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, deltaMinutes > 0 ? "Extending..." : "Updating...");
  }
}

async function toggleSchedule(scheduleId, enabled, button) {
  setBusy(button, true, enabled ? "Enabling..." : "Disabling...");
  try {
    const response = await api(`/api/schedules/${encodeURIComponent(scheduleId)}/toggle`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
    renderSchedules(response.schedules || []);
    renderTimeline(response.upcoming_events || []);
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, enabled ? "Enabling..." : "Disabling...");
  }
}

async function deleteSchedule(scheduleId, button) {
  setBusy(button, true, "Deleting...");
  try {
    const response = await api(`/api/schedules/${encodeURIComponent(scheduleId)}`, {
      method: "DELETE",
    });
    renderSchedules(response.schedules || []);
    renderTimeline(response.upcoming_events || []);
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, "Deleting...");
  }
}

async function refreshAllStates() {
  setBusy(refreshButton, true, "Refreshing...");
  panelStatusEl.textContent = "Refreshing device states...";
  try {
    await loadDevices({ refresh: true });
  } catch (error) {
    showAlerts([error.message], "error");
    panelStatusEl.textContent = "Refresh failed.";
  } finally {
    setBusy(refreshButton, false, "Refreshing...");
  }
}

async function handleDeviceAction(deviceId, action, button) {
  setBusy(button, true, action === "refresh" ? "Refreshing..." : "Working...");
  try {
    const endpoint = action === "refresh"
      ? `/api/devices/${encodeURIComponent(deviceId)}/refresh`
      : `/api/devices/${encodeURIComponent(deviceId)}/${action}`;
    const payload = await api(endpoint, { method: "POST" });
    addAlert(payload.message, "success");
    await loadDevices({ refresh: false });
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, action === "refresh" ? "Refreshing..." : "Working...");
  }
}

async function handleBrightnessChange(deviceId, brightness, button) {
  setBusy(button, true, "Applying...");
  try {
    const payload = await api(
      `/api/devices/${encodeURIComponent(deviceId)}/brightness`,
      {
        method: "POST",
        body: JSON.stringify({ brightness }),
      },
    );
    addAlert(payload.message, "success");
    await loadDevices({ refresh: false });
  } catch (error) {
    showAlerts([error.message], "error");
  } finally {
    setBusy(button, false, "Applying...");
  }
}

function startPolling() {
  if (state.pollHandle || !pollSeconds) {
    return;
  }
  state.pollHandle = window.setInterval(() => {
    if (document.hidden) {
      return;
    }
    loadDevices({ refresh: true }).catch((error) => {
      showAlerts([error.message], "error");
    });
  }, pollSeconds * 1000);
}

discoverButton.addEventListener("click", discoverDevices);
refreshButton.addEventListener("click", refreshAllStates);
manualForm.addEventListener("submit", addManualAddress);
scheduleForm.addEventListener("submit", createSchedule);
scheduleCancelEditButton.addEventListener("click", resetScheduleForm);
scheduleTypeSelect.addEventListener("change", refreshScheduleFormVisibility);
scheduleActionSelect.addEventListener("change", refreshScheduleFormVisibility);
scheduleDeviceSelect.addEventListener("change", syncScheduleEditorForDeviceChange);
scheduleBrightnessInput.addEventListener("input", () => {
  scheduleBrightnessValue.textContent = `${scheduleBrightnessInput.value}%`;
});

window.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadManualAddresses();
    await discoverDevices();
    await loadSchedules();
    resetScheduleForm();
    startPolling();
    startScheduleCountdowns();
  } catch (error) {
    showAlerts([error.message], "error");
  }
});
