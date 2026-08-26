"use strict";

export async function readBridgeStatus(
  root = document,
  invoke = globalThis.__TAURI__.core.invoke,
) {
  const runtimeState = root.querySelector("#runtime-state");
  const adapterState = root.querySelector("#adapter-state");
  const statusMessage = root.querySelector("#status-message");
  try {
    const status = await invoke("desktop_bridge_status");
    runtimeState.textContent = status.ready ? "Ready" : "Protected";
    adapterState.textContent = status.code;
    statusMessage.textContent = status.message;
  } catch (_error) {
    runtimeState.textContent = "Unavailable";
    adapterState.textContent = "IPC denied";
    statusMessage.textContent = "The desktop runtime did not expose the expected status command.";
  }
}

if (typeof document !== "undefined") {
  void readBridgeStatus();
}
