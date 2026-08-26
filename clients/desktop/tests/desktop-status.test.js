import assert from "node:assert/strict";
import test from "node:test";

import { readBridgeStatus } from "../frontend/desktop.js";

function statusRoot() {
  const values = new Map([
    ["#runtime-state", { textContent: "Checking" }],
    ["#adapter-state", { textContent: "Default deny" }],
    ["#status-message", { textContent: "Validating" }],
  ]);
  return {
    querySelector(selector) {
      return values.get(selector);
    },
    value(selector) {
      return values.get(selector).textContent;
    },
  };
}

test("readBridgeStatus renders the protected zero-action state", async () => {
  const root = statusRoot();
  const calls = [];
  await readBridgeStatus(root, async (command) => {
    calls.push(command);
    return {
      ready: false,
      code: "DESKTOP_SESSION_REQUIRED",
      message: "Local invocation remains disabled.",
    };
  });

  assert.deepEqual(calls, ["desktop_bridge_status"]);
  assert.equal(root.value("#runtime-state"), "Protected");
  assert.equal(root.value("#adapter-state"), "DESKTOP_SESSION_REQUIRED");
  assert.equal(root.value("#status-message"), "Local invocation remains disabled.");
});

test("readBridgeStatus reports denied IPC without exposing error detail", async () => {
  const root = statusRoot();
  await readBridgeStatus(root, async () => {
    throw new Error("provider detail must not be rendered");
  });

  assert.equal(root.value("#runtime-state"), "Unavailable");
  assert.equal(root.value("#adapter-state"), "IPC denied");
  assert.equal(
    root.value("#status-message"),
    "The desktop runtime did not expose the expected status command.",
  );
});
