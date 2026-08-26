use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

const BRIDGE_SCHEMA_VERSION: &str = "1.0.0";
const TOOL_VERSION: &str = "1.0.0";
const MAX_ARGUMENT_BYTES: usize = 1024;
const MAX_IDEMPOTENCY_BYTES: usize = 128;
const ALLOWED_TOOLS: [&str; 6] = [
    "adapter.reference.ae.acquire",
    "adapter.reference.gpr.acquire",
    "adapter.reference.ie.acquire",
    "adapter.reference.mv.acquire",
    "adapter.reference.rt.acquire",
    "adapter.reference.ut.acquire",
];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeStatus {
    schema_version: &'static str,
    ready: bool,
    code: &'static str,
    message: &'static str,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BridgeRequest {
    schema_version: String,
    session_handle: String,
    task_id: Uuid,
    run_id: Uuid,
    registry_version: String,
    tool_name: String,
    tool_version: String,
    arguments: Value,
    idempotency_key: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeResult {
    schema_version: &'static str,
    request_sha256: String,
    tool_name: String,
    tool_version: String,
    output: Value,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct BridgeError {
    code: &'static str,
    message: &'static str,
    next_action: &'static str,
}

impl BridgeError {
    fn invalid(message: &'static str) -> Self {
        Self {
            code: "DESKTOP_REQUEST_INVALID",
            message,
            next_action: "Discard the request and rebuild it from the versioned desktop contract.",
        }
    }

    fn session_required() -> Self {
        Self {
            code: "DESKTOP_SESSION_REQUIRED",
            message: "No application-owned authenticated desktop session is installed.",
            next_action: "Install a scoped session adapter before enabling local invocation.",
        }
    }

    #[allow(dead_code)]
    fn executor_unavailable() -> Self {
        Self {
            code: "DESKTOP_EXECUTOR_UNAVAILABLE",
            message: "No registry-bound local adapter executor is installed.",
            next_action: "Install and qualify the fixed application-owned executor adapter.",
        }
    }
}

impl BridgeRequest {
    fn validate(&self) -> Result<String, BridgeError> {
        if self.schema_version != BRIDGE_SCHEMA_VERSION {
            return Err(BridgeError::invalid(
                "The bridge schema version is unsupported.",
            ));
        }
        if self.session_handle.len() < 32
            || self.session_handle.len() > 128
            || !self
                .session_handle
                .bytes()
                .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_'))
        {
            return Err(BridgeError::invalid(
                "The opaque session handle is malformed.",
            ));
        }
        if self.task_id.is_nil() || self.run_id.is_nil() {
            return Err(BridgeError::invalid(
                "Task and run identities must be non-nil UUIDs.",
            ));
        }
        if self.registry_version.is_empty()
            || self.registry_version.len() > 128
            || self.registry_version.trim() != self.registry_version
        {
            return Err(BridgeError::invalid("The registry version is malformed."));
        }
        if !ALLOWED_TOOLS.contains(&self.tool_name.as_str()) || self.tool_version != TOOL_VERSION {
            return Err(BridgeError::invalid(
                "The tool is outside the compiled desktop allowlist.",
            ));
        }
        if !self.arguments.is_object() {
            return Err(BridgeError::invalid(
                "Tool arguments must be one strict JSON object.",
            ));
        }
        let argument_bytes = serde_json::to_vec(&self.arguments)
            .map_err(|_| BridgeError::invalid("Tool arguments cannot be serialized."))?;
        if argument_bytes.len() > MAX_ARGUMENT_BYTES {
            return Err(BridgeError::invalid(
                "Tool arguments exceed the desktop byte budget.",
            ));
        }
        if self.idempotency_key.len() < 8
            || self.idempotency_key.len() > MAX_IDEMPOTENCY_BYTES
            || self.idempotency_key.trim() != self.idempotency_key
        {
            return Err(BridgeError::invalid("The idempotency key is malformed."));
        }

        let mut hasher = Sha256::new();
        hasher.update(BRIDGE_SCHEMA_VERSION.as_bytes());
        hasher.update(self.session_handle.as_bytes());
        hasher.update(self.task_id.as_bytes());
        hasher.update(self.run_id.as_bytes());
        hasher.update(self.registry_version.as_bytes());
        hasher.update(self.tool_name.as_bytes());
        hasher.update(self.tool_version.as_bytes());
        hasher.update(argument_bytes);
        hasher.update(self.idempotency_key.as_bytes());
        let digest = hasher.finalize();
        let mut encoded = String::with_capacity(digest.len() * 2);
        const HEX: &[u8; 16] = b"0123456789abcdef";
        for byte in digest {
            encoded.push(HEX[(byte >> 4) as usize] as char);
            encoded.push(HEX[(byte & 0x0f) as usize] as char);
        }
        Ok(encoded)
    }
}

#[tauri::command]
pub fn desktop_bridge_status() -> BridgeStatus {
    BridgeStatus {
        schema_version: BRIDGE_SCHEMA_VERSION,
        ready: false,
        code: "DESKTOP_SESSION_REQUIRED",
        message: "The native boundary is active; local adapter invocation remains disabled.",
    }
}

#[tauri::command]
pub fn desktop_bridge_invoke(request: BridgeRequest) -> Result<BridgeResult, BridgeError> {
    let _request_sha256 = request.validate()?;
    Err(BridgeError::session_required())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn request() -> BridgeRequest {
        BridgeRequest {
            schema_version: BRIDGE_SCHEMA_VERSION.to_owned(),
            session_handle: "desktop-session-handle-000000000001".to_owned(),
            task_id: Uuid::parse_str("00000000-0000-4000-8000-000000000601").unwrap(),
            run_id: Uuid::parse_str("00000000-0000-4000-8000-000000000602").unwrap(),
            registry_version: "registry-s5-1".to_owned(),
            tool_name: "adapter.reference.ut.acquire".to_owned(),
            tool_version: TOOL_VERSION.to_owned(),
            arguments: json!({"fixture_id": "reference-ut-default"}),
            idempotency_key: "desktop-call-0001".to_owned(),
        }
    }

    #[test]
    fn valid_request_hash_is_stable() {
        let first = request().validate().unwrap();
        let second = request().validate().unwrap();
        assert_eq!(first, second);
        assert_eq!(first.len(), 64);
    }

    #[test]
    fn malformed_unknown_and_oversized_requests_fail_closed() {
        let mut wrong_tool = request();
        wrong_tool.tool_name = "adapter.unregistered.acquire".to_owned();
        assert_eq!(
            wrong_tool.validate().unwrap_err().code,
            "DESKTOP_REQUEST_INVALID"
        );

        let mut oversized = request();
        oversized.arguments = json!({"value": "x".repeat(MAX_ARGUMENT_BYTES + 1)});
        assert_eq!(
            oversized.validate().unwrap_err().code,
            "DESKTOP_REQUEST_INVALID"
        );

        let unknown = serde_json::from_value::<BridgeRequest>(json!({
            "schemaVersion": BRIDGE_SCHEMA_VERSION,
            "sessionHandle": "desktop-session-handle-000000000001",
            "taskId": "00000000-0000-4000-8000-000000000601",
            "runId": "00000000-0000-4000-8000-000000000602",
            "registryVersion": "registry-s5-1",
            "toolName": "adapter.reference.ut.acquire",
            "toolVersion": TOOL_VERSION,
            "arguments": {"fixture_id": "reference-ut-default"},
            "idempotencyKey": "desktop-call-0001",
            "grantedPermissions": ["reference.ut.acquire"]
        }));
        assert!(unknown.is_err());
    }

    #[test]
    fn invocation_stops_before_any_executor_without_an_authoritative_session() {
        let error = desktop_bridge_invoke(request()).unwrap_err();
        assert_eq!(error.code, "DESKTOP_SESSION_REQUIRED");
        assert!(!desktop_bridge_status().ready);
    }
}
