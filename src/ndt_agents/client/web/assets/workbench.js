"use strict";

const form = document.querySelector("#task-form");
const eventList = document.querySelector("#event-list");
const emptyState = document.querySelector("#empty-state");
const taskState = document.querySelector("#task-state");
const reviewState = document.querySelector("#review-state");
const taskMeta = document.querySelector("#task-meta");
const liveStatus = document.querySelector("#live-status");
const connectionLabel = document.querySelector("#connection-label");
const actionPanel = document.querySelector("#action-panel");
const issueCode = document.querySelector("#issue-code");
const issueMessage = document.querySelector("#issue-message");
const nextAction = document.querySelector("#next-action");
const resumeButton = document.querySelector("#resume-events");
let activeTask = null;
let lastSequence = 0;
let stopped = false;
let capabilitiesReady = false;
let creating = false;
let polling = false;

const routeLabels = {
  G0: "General analysis",
  P1: "Professional synchronous",
};

function updateConnection() {
  if (!navigator.onLine) connectionLabel.textContent = "Offline / read-only shell";
  else if (activeTask && !stopped && !polling) connectionLabel.textContent = "Ready to resume";
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

async function loadCapabilities() {
  const select = form.elements.task_class;
  const button = form.querySelector("button");
  try {
    const response = await fetch("/v1/workbench/capabilities", {
      headers: authHeaders(), credentials: "same-origin", cache: "no-store"
    });
    await requireOk(
      response,
      "An authenticated workbench session is required.",
      "WORKBENCH_CAPABILITIES_UNAVAILABLE",
      "Restore the authenticated same-origin session and reload capabilities."
    );
    const capabilities = await response.json();
    const options = capabilities.task_classes.map((taskClass) => {
      const option = document.createElement("option");
      option.value = taskClass;
      option.textContent = routeLabels[taskClass] || taskClass;
      return option;
    });
    select.replaceChildren(...options);
    capabilitiesReady = options.length > 0;
    select.disabled = !capabilitiesReady;
    button.disabled = !capabilitiesReady;
    connectionLabel.textContent = capabilitiesReady ? "Session ready" : "No execution route enabled";
  } catch (error) {
    capabilitiesReady = false;
    select.replaceChildren();
    select.disabled = true;
    button.disabled = true;
    connectionLabel.textContent = "Session required";
    showAction(
      error,
      "WORKBENCH_CAPABILITIES_UNAVAILABLE",
      "Restore the authenticated same-origin session and reload capabilities."
    );
  }
}

function authHeaders() {
  const provider = globalThis.ndtWorkbenchAuthHeaders;
  return typeof provider === "function" ? provider() : {};
}

function requestError(payload, fallbackMessage, fallbackCode, fallbackNextAction) {
  const error = new Error(
    typeof payload?.message === "string" && payload.message ? payload.message : fallbackMessage
  );
  error.code = typeof payload?.error_code === "string" && payload.error_code
    ? payload.error_code : fallbackCode;
  error.nextAction = typeof payload?.next_action === "string" && payload.next_action
    ? payload.next_action : fallbackNextAction;
  return error;
}

async function requireOk(response, fallbackMessage, fallbackCode, fallbackNextAction) {
  if (response.ok) return;
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  throw requestError(payload, fallbackMessage, fallbackCode, fallbackNextAction);
}

function clearAction() {
  actionPanel.hidden = true;
  issueCode.textContent = "WORKBENCH_ACTION_REQUIRED";
  issueMessage.textContent = "Inspect the latest task event.";
  nextAction.textContent = "Review the task evidence.";
  resumeButton.hidden = true;
  resumeButton.disabled = false;
}

function showAction(error, fallbackCode, fallbackNextAction) {
  const message = typeof error?.message === "string" && error.message
    ? error.message : "The workbench action stopped.";
  issueCode.textContent = typeof error?.code === "string" ? error.code : fallbackCode;
  issueMessage.textContent = message;
  nextAction.textContent = typeof error?.nextAction === "string"
    ? error.nextAction : fallbackNextAction;
  actionPanel.hidden = false;
  liveStatus.textContent = `${issueCode.textContent}: ${message} Next action: ${nextAction.textContent}`;
}

loadCapabilities();

function renderEvent(event) {
  if (!Number.isInteger(event.sequence) || event.sequence < 1) {
    throw requestError(
      {},
      "The event stream returned an invalid sequence.",
      "CLIENT_EVENT_SEQUENCE_INVALID",
      "Resume from the last acknowledged event after the service is corrected."
    );
  }
  if (event.sequence <= lastSequence) return;
  if (event.sequence !== lastSequence + 1) {
    throw requestError(
      {},
      "The event stream contains a sequence gap.",
      "CLIENT_EVENT_SEQUENCE_GAP",
      `Resume from acknowledged sequence ${lastSequence}.`
    );
  }
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
  if (event.kind === "REVIEW" && event.state === "RUNNING") reviewState.textContent = "Passed";
  if (event.kind === "ISSUE" && event.state === "FAILED" && reviewState.textContent === "In progress") {
    reviewState.textContent = "Stopped";
  }
  if (event.error_code || event.next_action) {
    showAction(
      {
        code: event.error_code,
        message: event.message,
        nextAction: event.next_action,
      },
      "CLIENT_TASK_ACTION_REQUIRED",
      "Inspect the sanitized task evidence."
    );
  }
  liveStatus.textContent = `Task event ${event.sequence}: ${event.message}`;
}

function processEventBlock(block) {
  const lines = block.replaceAll("\r\n", "\n").split("\n");
  const eventName = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines.filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6)).join("\n");
  if (!data) return;
  const payload = JSON.parse(data);
  if (eventName === "task-event") renderEvent(payload);
  if (eventName === "stream-state") {
    if (payload.last_sequence !== lastSequence) {
      throw requestError(
        {},
        "The event stream cursor does not match the rendered timeline.",
        "CLIENT_EVENT_CURSOR_MISMATCH",
        `Resume from acknowledged sequence ${lastSequence}.`
      );
    }
    stopped = payload.terminal === true;
  }
}

async function readEventStream(response) {
  if (!response.body || typeof response.body.getReader !== "function") {
    const text = (await response.text()).replaceAll("\r\n", "\n");
    for (const block of text.split("\n\n")) processEventBlock(block);
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value, {stream: !done});
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      processEventBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) processEventBlock(buffer);
}

async function pollEvents() {
  if (!activeTask || stopped || polling) return;
  polling = true;
  clearAction();
  resumeButton.disabled = true;
  resumeButton.hidden = true;
  try {
    connectionLabel.textContent = "Connecting";
    const query = new URLSearchParams({task_id: activeTask, after_sequence: String(lastSequence)});
    const response = await fetch(`/v1/workbench/events?${query}`, {
      headers: authHeaders(), credentials: "same-origin", cache: "no-store"
    });
    await requireOk(
      response,
      "The event stream is unavailable.",
      "CLIENT_EVENT_STREAM_UNAVAILABLE",
      `Resume from acknowledged sequence ${lastSequence}.`
    );
    connectionLabel.textContent = "Connected";
    await readEventStream(response);
    if (stopped) {
      connectionLabel.textContent = "Task complete";
    } else {
      connectionLabel.textContent = "Task still running";
      showAction(
        requestError(
          {},
          "The task has no terminal event yet.",
          "CLIENT_EVENT_STREAM_CONTINUE_REQUIRED",
          `Resume from acknowledged sequence ${lastSequence}.`
        ),
        "CLIENT_EVENT_STREAM_CONTINUE_REQUIRED",
        `Resume from acknowledged sequence ${lastSequence}.`
      );
      resumeButton.hidden = false;
    }
  } catch (error) {
    connectionLabel.textContent = "Action required";
    showAction(
      error,
      "CLIENT_EVENT_STREAM_UNAVAILABLE",
      `Resume from acknowledged sequence ${lastSequence}.`
    );
    resumeButton.hidden = !activeTask || stopped;
  } finally {
    polling = false;
    resumeButton.disabled = false;
  }
}

resumeButton.addEventListener("click", () => {
  if (!navigator.onLine) {
    connectionLabel.textContent = "Offline / no request sent";
    liveStatus.textContent = "Reconnect before resuming the event stream.";
    return;
  }
  void pollEvents();
});

form.addEventListener("submit", async (submitEvent) => {
  submitEvent.preventDefault();
  if (creating || polling) return;
  if (!capabilitiesReady) {
    liveStatus.textContent = "No authenticated execution route is enabled.";
    return;
  }
  if (!navigator.onLine) {
    liveStatus.textContent = "Task creation is unavailable offline. Reconnect and submit again.";
    connectionLabel.textContent = "Offline / no task queued";
    return;
  }
  const button = form.querySelector("button");
  const criteria = form.elements.criteria.value.split("\n").map((item) => item.trim()).filter(Boolean);
  creating = true;
  button.disabled = true;
  connectionLabel.textContent = "Creating task";
  clearAction();
  try {
    const response = await fetch("/v1/workbench/tasks", {
      method: "POST", headers: {...authHeaders(), "content-type": "application/json"},
      credentials: "same-origin", cache: "no-store",
      body: JSON.stringify({schema_version: "1.0.0", task_class: form.elements.task_class.value,
        goal: form.elements.goal.value.trim(), success_criteria: criteria,
        idempotency_key: crypto.randomUUID()})
    });
    await requireOk(
      response,
      "The task could not be created.",
      "CLIENT_TASK_CREATE_FAILED",
      "Correct the request or restore the authenticated session before submitting again."
    );
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
    showAction(
      error,
      "CLIENT_TASK_CREATE_FAILED",
      "Correct the request or restore the authenticated session before submitting again."
    );
  } finally {
    creating = false;
    button.disabled = !capabilitiesReady;
  }
});
