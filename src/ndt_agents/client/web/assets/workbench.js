"use strict";

const form = document.querySelector("#task-form");
const eventList = document.querySelector("#event-list");
const emptyState = document.querySelector("#empty-state");
const taskState = document.querySelector("#task-state");
const reviewState = document.querySelector("#review-state");
const taskMeta = document.querySelector("#task-meta");
const liveStatus = document.querySelector("#live-status");
const connectionLabel = document.querySelector("#connection-label");
let activeTask = null;
let lastSequence = 0;
let stopped = false;

function updateConnection() {
  if (!navigator.onLine) connectionLabel.textContent = "Offline / read-only shell";
  else if (!activeTask) connectionLabel.textContent = "Session required";
}

window.addEventListener("online", updateConnection);
window.addEventListener("offline", updateConnection);
updateConnection();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/workbench/sw.js", {scope: "/workbench"}).catch(() => {
    connectionLabel.textContent = "Install support unavailable";
  });
}

function authHeaders() {
  const provider = globalThis.ndtWorkbenchAuthHeaders;
  return typeof provider === "function" ? provider() : {};
}

function renderEvent(event) {
  const item = document.createElement("li");
  const sequence = document.createElement("span");
  const detail = document.createElement("div");
  const kind = document.createElement("p");
  const message = document.createElement("p");
  sequence.className = "event-sequence";
  sequence.textContent = String(event.sequence).padStart(2, "0");
  kind.className = "event-kind";
  kind.textContent = `${event.kind} / ${event.state}`;
  message.className = "event-message";
  message.textContent = event.message;
  detail.append(kind, message);
  item.append(sequence, detail);
  eventList.append(item);
  emptyState.hidden = true;
  lastSequence = event.sequence;
  taskState.textContent = event.state.replaceAll("_", " ");
  if (event.kind === "REVIEW" && event.state === "REVIEW_REQUIRED") reviewState.textContent = "In progress";
  if (event.kind === "REVIEW" && event.state === "RUNNING") reviewState.textContent = "Completed";
  liveStatus.textContent = `Task event ${event.sequence}: ${event.message}`;
}

async function readEventStream(response) {
  const text = await response.text();
  for (const block of text.split("\n\n")) {
    const eventName = block.split("\n").find((line) => line.startsWith("event: "))?.slice(7);
    const data = block.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
    if (!data) continue;
    const payload = JSON.parse(data);
    if (eventName === "task-event") renderEvent(payload);
    if (eventName === "stream-state" && payload.terminal) stopped = true;
  }
}

async function pollEvents() {
  while (activeTask && !stopped) {
    connectionLabel.textContent = "Connecting";
    const query = new URLSearchParams({task_id: activeTask, after_sequence: String(lastSequence)});
    const response = await fetch(`/v1/workbench/events?${query}`, {
      headers: authHeaders(), credentials: "same-origin", cache: "no-store"
    });
    if (!response.ok) throw new Error("The event stream is unavailable.");
    connectionLabel.textContent = "Connected";
    await readEventStream(response);
    if (!stopped) await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  if (stopped) connectionLabel.textContent = "Task complete";
}

form.addEventListener("submit", async (submitEvent) => {
  submitEvent.preventDefault();
  if (!navigator.onLine) {
    liveStatus.textContent = "Task creation is unavailable offline. Reconnect and submit again.";
    connectionLabel.textContent = "Offline / no task queued";
    return;
  }
  const button = form.querySelector("button");
  const criteria = form.elements.criteria.value.split("\n").map((item) => item.trim()).filter(Boolean);
  button.disabled = true;
  connectionLabel.textContent = "Creating task";
  try {
    const response = await fetch("/v1/workbench/tasks", {
      method: "POST", headers: {...authHeaders(), "content-type": "application/json"},
      credentials: "same-origin", cache: "no-store",
      body: JSON.stringify({schema_version: "1.0.0", task_class: form.elements.task_class.value,
        goal: form.elements.goal.value.trim(), success_criteria: criteria,
        idempotency_key: crypto.randomUUID()})
    });
    if (!response.ok) throw new Error("The task could not be created.");
    const task = await response.json();
    activeTask = task.task_id;
    lastSequence = 0;
    stopped = false;
    eventList.replaceChildren();
    taskMeta.textContent = `Task ${task.task_id} / ${task.task_class}`;
    reviewState.textContent = task.review_required ? "Required" : "Rules path";
    await pollEvents();
  } catch (error) {
    connectionLabel.textContent = "Action required";
    liveStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
