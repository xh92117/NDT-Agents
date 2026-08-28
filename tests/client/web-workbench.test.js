"use strict";

const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {resolve} = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SCRIPT = readFileSync(
  resolve(__dirname, "../../src/ndt_agents/client/web/assets/workbench.js"),
  "utf8"
);

class FakeElement {
  constructor(name) {
    this.name = name;
    this.children = [];
    this.listeners = new Map();
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.elements = {};
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  querySelector(selector) {
    if (selector === "button") return this.submitButton;
    return null;
  }

  emit(type, event = {}) {
    const listener = this.listeners.get(type);
    if (!listener) throw new Error(`No ${type} listener for ${this.name}`);
    return listener(event);
  }
}

function response({ok = true, json = {}, text = ""} = {}) {
  return {
    ok,
    async json() {
      return json;
    },
    async text() {
      return text;
    },
  };
}

function taskEvent(sequence, kind, state, updates = {}) {
  return {
    sequence,
    kind,
    state,
    message: `${kind} ${state}`,
    ...updates,
  };
}

function eventStream(events, {lastSequence, terminal}) {
  const blocks = events.map(
    (event) => `event: task-event\ndata: ${JSON.stringify(event)}`
  );
  blocks.push(
    `event: stream-state\ndata: ${JSON.stringify({last_sequence: lastSequence, terminal})}`
  );
  return `${blocks.join("\n\n")}\n\n`;
}

function controlledChunkedResponse(firstText, finalText) {
  const encoder = new TextEncoder();
  const first = encoder.encode(firstText);
  const final = encoder.encode(finalText);
  const split = Math.max(1, first.indexOf(0xe5) + 1);
  const chunks = [first.slice(0, split), first.slice(split)];
  let releaseFinal;
  let index = 0;
  return {
    response: {
      ok: true,
      body: {
        getReader() {
          return {
            async read() {
              if (index < chunks.length) return {value: chunks[index++], done: false};
              if (index++ === chunks.length) {
                return await new Promise((resolveRead) => {
                  releaseFinal = () => resolveRead({value: final, done: false});
                });
              }
              return {value: undefined, done: true};
            },
          };
        },
      },
    },
    release() {
      if (!releaseFinal) throw new Error("stream final reader is not waiting");
      releaseFinal();
    },
  };
}

function harness(initialResponses) {
  const names = [
    "#task-form",
    "#event-list",
    "#empty-state",
    "#task-state",
    "#review-state",
    "#task-meta",
    "#live-status",
    "#connection-label",
    "#action-panel",
    "#issue-code",
    "#issue-message",
    "#next-action",
    "#resume-events",
  ];
  const elements = Object.fromEntries(names.map((name) => [name, new FakeElement(name)]));
  const select = new FakeElement("task_class");
  const goal = new FakeElement("goal");
  const criteria = new FakeElement("criteria");
  const submitButton = new FakeElement("submit");
  const form = elements["#task-form"];
  form.elements = {task_class: select, goal, criteria};
  form.submitButton = submitButton;
  elements["#action-panel"].hidden = true;
  elements["#resume-events"].hidden = true;
  const queue = [...initialResponses];
  const calls = [];
  const windowListeners = new Map();

  const context = {
    console,
    crypto: {randomUUID: () => "00000000-0000-4000-8000-000000000701"},
    document: {
      createElement: (name) => new FakeElement(name),
      querySelector: (selector) => elements[selector],
    },
    fetch: async (url, options) => {
      calls.push({url: String(url), options});
      if (queue.length === 0) throw new Error(`Unexpected fetch for ${url}`);
      const next = queue.shift();
      if (typeof next === "function") return await next();
      if (next instanceof Error) throw next;
      return next;
    },
    navigator: {
      onLine: true,
      serviceWorker: {register: async () => ({scope: "/workbench"})},
    },
    ndtWorkbenchAuthHeaders: () => ({"x-test-session": "present"}),
    setTimeout,
    TextDecoder,
    TextEncoder,
    URLSearchParams,
    window: {
      addEventListener: (type, listener) => windowListeners.set(type, listener),
    },
  };
  vm.createContext(context);
  vm.runInContext(SCRIPT, context, {filename: "workbench.js"});
  return {calls, context, elements, form, queue, select, submitButton};
}

async function flush() {
  await new Promise((resolveFlush) => setImmediate(resolveFlush));
  await new Promise((resolveFlush) => setImmediate(resolveFlush));
}

function capabilityResponse() {
  return response({
    json: {
      schema_version: "1.0.0",
      execution_mode: "REVIEWED_PROFESSIONAL",
      task_classes: ["G0", "P1"],
      limitations: ["SYNTHETIC only"],
    },
  });
}

function taskResponse() {
  return response({
    json: {
      task_id: "00000000-0000-4000-8000-000000000702",
      task_class: "P1",
      review_required: true,
    },
  });
}

test("renders a typed failed review with its actionable next step", async () => {
  const events = [
    taskEvent(1, "STATUS", "ACCEPTED"),
    taskEvent(2, "STATUS", "RUNNING"),
    taskEvent(3, "REVIEW", "REVIEW_REQUIRED"),
    taskEvent(4, "ISSUE", "FAILED", {
      error_code: "MODEL_OUTPUT_SCHEMA_INVALID",
      next_action: "Inspect the sanitized model response before another explicit run.",
    }),
  ];
  const app = harness([
    capabilityResponse(),
    taskResponse(),
    response({text: eventStream(events, {lastSequence: 4, terminal: true})}),
  ]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Check the synthetic result.";
  app.form.elements.criteria.value = "Preserve scope";

  await app.form.emit("submit", {preventDefault() {}});

  assert.equal(app.elements["#action-panel"].hidden, false);
  assert.equal(app.elements["#issue-code"].textContent, "MODEL_OUTPUT_SCHEMA_INVALID");
  assert.equal(app.elements["#issue-message"].textContent, "ISSUE FAILED");
  assert.equal(
    app.elements["#next-action"].textContent,
    "Inspect the sanitized model response before another explicit run."
  );
  assert.equal(app.elements["#task-state"].textContent, "FAILED");
  assert.equal(app.elements["#review-state"].textContent, "Stopped");
  assert.equal(app.elements["#connection-label"].textContent, "Task complete");
  assert.equal(app.elements["#resume-events"].hidden, true);
  assert.equal(app.elements["#event-list"].children.length, 4);
});

test("renders split UTF-8 SSE chunks before the bounded connection closes", async () => {
  const accepted = taskEvent(1, "STATUS", "ACCEPTED", {message: "合成检查已接受"});
  const running = taskEvent(2, "STATUS", "RUNNING");
  const succeeded = taskEvent(3, "RESULT", "SUCCEEDED");
  const stream = controlledChunkedResponse(
    eventStream([accepted], {lastSequence: 1, terminal: false}),
    eventStream([running, succeeded], {lastSequence: 3, terminal: true})
  );
  const app = harness([capabilityResponse(), taskResponse(), stream.response]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Render streamed UTF-8 events.";
  app.form.elements.criteria.value = "Render before close";

  const submitted = app.form.emit("submit", {preventDefault() {}});
  await flush();
  assert.equal(app.elements["#event-list"].children.length, 1);
  assert.equal(
    app.elements["#event-list"].children[0].children[1].children[1].textContent,
    "合成检查已接受"
  );

  stream.release();
  await submitted;
  assert.equal(app.elements["#event-list"].children.length, 3);
  assert.equal(app.elements["#connection-label"].textContent, "Task complete");
});

test("resumes once from the acknowledged cursor and ignores a duplicate event", async () => {
  const firstBatch = eventStream(
    [taskEvent(1, "STATUS", "ACCEPTED")],
    {lastSequence: 1, terminal: false}
  );
  const app = harness([
    capabilityResponse(),
    taskResponse(),
    response({text: firstBatch}),
  ]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Check resumable events.";
  app.form.elements.criteria.value = "No duplicate event";
  await app.form.emit("submit", {preventDefault() {}});
  assert.equal(app.elements["#resume-events"].hidden, false);
  assert.match(app.calls[2].url, /after_sequence=0/);

  let releaseResume;
  app.queue.push(
    () => new Promise((resolveResume) => {
      releaseResume = resolveResume;
    })
  );
  app.elements["#resume-events"].emit("click");
  app.elements["#resume-events"].emit("click");
  await flush();
  assert.equal(app.calls.length, 4, "concurrent resume clicks must make one request");
  assert.match(app.calls[3].url, /after_sequence=1/);

  releaseResume(response({
    text: eventStream(
      [
        taskEvent(1, "STATUS", "ACCEPTED"),
        taskEvent(2, "RESULT", "SUCCEEDED"),
      ],
      {lastSequence: 2, terminal: true}
    ),
  }));
  await flush();

  assert.equal(app.elements["#event-list"].children.length, 2);
  assert.deepEqual(
    app.elements["#event-list"].children.map((item) => item.children[0].textContent),
    ["01", "02"]
  );
  assert.equal(app.elements["#connection-label"].textContent, "Task complete");
  assert.equal(app.elements["#resume-events"].hidden, true);
});

test("shows typed capability denial and keeps task creation disabled", async () => {
  const app = harness([
    response({
      ok: false,
      json: {
        error_code: "AUTH_PERMISSION_DENIED",
        message: "The workbench capability is not authorized.",
        next_action: "Request the workbench capability-read permission.",
      },
    }),
  ]);
  await flush();

  assert.equal(app.elements["#action-panel"].hidden, false);
  assert.equal(app.elements["#issue-code"].textContent, "AUTH_PERMISSION_DENIED");
  assert.equal(
    app.elements["#next-action"].textContent,
    "Request the workbench capability-read permission."
  );
  assert.equal(app.submitButton.disabled, true);
  assert.equal(app.calls.length, 1);
});

test("stops on an event gap and preserves the last acknowledged cursor", async () => {
  const app = harness([
    capabilityResponse(),
    taskResponse(),
    response({
      text: eventStream(
        [taskEvent(2, "STATUS", "RUNNING")],
        {lastSequence: 2, terminal: false}
      ),
    }),
  ]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Detect an event gap.";
  app.form.elements.criteria.value = "Preserve the cursor";

  await app.form.emit("submit", {preventDefault() {}});

  assert.equal(app.elements["#event-list"].children.length, 0);
  assert.equal(app.elements["#issue-code"].textContent, "CLIENT_EVENT_SEQUENCE_GAP");
  assert.equal(app.elements["#next-action"].textContent, "Resume from acknowledged sequence 0.");
  assert.equal(app.elements["#resume-events"].hidden, false);
});

test("rejects malformed SSE data and keeps explicit resume available", async () => {
  const app = harness([
    capabilityResponse(),
    taskResponse(),
    response({text: "event: task-event\ndata: {malformed-json}\n\n"}),
  ]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Reject malformed stream data.";
  app.form.elements.criteria.value = "Keep the cursor stable";

  await app.form.emit("submit", {preventDefault() {}});

  assert.equal(app.elements["#event-list"].children.length, 0);
  assert.equal(app.elements["#issue-code"].textContent, "CLIENT_EVENT_STREAM_UNAVAILABLE");
  assert.equal(app.elements["#resume-events"].hidden, false);
});

test("rejects a stream-state cursor mismatch after preserving rendered events", async () => {
  const app = harness([
    capabilityResponse(),
    taskResponse(),
    response({
      text: eventStream(
        [taskEvent(1, "STATUS", "ACCEPTED")],
        {lastSequence: 2, terminal: false}
      ),
    }),
  ]);
  await flush();
  app.select.value = "P1";
  app.form.elements.goal.value = "Reject a mismatched stream cursor.";
  app.form.elements.criteria.value = "Preserve rendered events";

  await app.form.emit("submit", {preventDefault() {}});

  assert.equal(app.elements["#event-list"].children.length, 1);
  assert.equal(app.elements["#issue-code"].textContent, "CLIENT_EVENT_CURSOR_MISMATCH");
  assert.equal(app.elements["#resume-events"].hidden, false);
});
