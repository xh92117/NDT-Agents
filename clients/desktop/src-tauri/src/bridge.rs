use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

const BRIDGE_SCHEMA_VERSION: &str = "1.0.0";
const TOOL_VERSION: &str = "1.0.0";
const MAX_ARGUMENT_BYTES: usize = 1024;
const MAX_CANCEL_REASON_BYTES: usize = 512;
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

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BridgeRequest {
    schema_version: String,
    operation: String,
    session_handle: String,
    task_id: Uuid,
    run_id: Uuid,
    registry_version: String,
    tool_name: String,
    tool_version: String,
    arguments: Value,
    idempotency_key: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CancelRequest {
    schema_version: String,
    operation: String,
    session_handle: String,
    task_id: Uuid,
    run_id: Uuid,
    registry_version: String,
    target_request_sha256: String,
    reason: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BridgeResult {
    schema_version: &'static str,
    request_sha256: String,
    tool_result: Value,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct BridgeError {
    schema_version: &'static str,
    code: &'static str,
    message: &'static str,
    next_action: &'static str,
    retryable: bool,
    request_sha256: Option<String>,
}

impl BridgeError {
    fn invalid(message: &'static str) -> Self {
        Self {
            schema_version: BRIDGE_SCHEMA_VERSION,
            code: "DESKTOP_REQUEST_INVALID",
            message,
            next_action: "Discard the request and rebuild it from the versioned desktop contract.",
            retryable: false,
            request_sha256: None,
        }
    }

    fn session_required(request_sha256: String) -> Self {
        Self {
            schema_version: BRIDGE_SCHEMA_VERSION,
            code: "DESKTOP_SESSION_REQUIRED",
            message: "No application-owned authenticated desktop session is installed.",
            next_action: "Install a scoped session adapter before enabling local invocation.",
            retryable: false,
            request_sha256: Some(request_sha256),
        }
    }

    fn cancel_unavailable(request_sha256: Option<String>) -> Self {
        Self {
            schema_version: BRIDGE_SCHEMA_VERSION,
            code: "DESKTOP_CANCEL_UNAVAILABLE",
            message: "No application-owned cancellation adapter is installed.",
            next_action: "Wait for the current operation to finish or install a qualified cancellation adapter.",
            retryable: false,
            request_sha256,
        }
    }

    #[allow(dead_code)]
    fn executor_unavailable() -> Self {
        Self {
            schema_version: BRIDGE_SCHEMA_VERSION,
            code: "DESKTOP_EXECUTOR_UNAVAILABLE",
            message: "No registry-bound local adapter executor is installed.",
            next_action: "Install and qualify the fixed application-owned executor adapter.",
            retryable: false,
            request_sha256: None,
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
        if self.operation != "INVOKE" {
            return Err(BridgeError::invalid("The bridge operation is invalid."));
        }
        if self.session_handle.len() < 32
            || self.session_handle.len() > 128
            || !self.session_handle.as_bytes()[0].is_ascii_alphanumeric()
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
        if !is_sha256(&self.registry_version) {
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
            || !self.idempotency_key.as_bytes()[0].is_ascii_alphanumeric()
            || !self.idempotency_key.bytes().all(|value| {
                value.is_ascii_alphanumeric() || matches!(value, b'.' | b'_' | b':' | b'-')
            })
        {
            return Err(BridgeError::invalid("The idempotency key is malformed."));
        }

        canonical_sha256(self)
    }
}

impl CancelRequest {
    fn validate(&self) -> Result<String, BridgeError> {
        if self.schema_version != BRIDGE_SCHEMA_VERSION || self.operation != "CANCEL" {
            return Err(BridgeError::invalid(
                "The cancellation schema or operation is invalid.",
            ));
        }
        if self.session_handle.len() < 32
            || self.session_handle.len() > 128
            || !self.session_handle.as_bytes()[0].is_ascii_alphanumeric()
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
        if !is_sha256(&self.registry_version) || !is_sha256(&self.target_request_sha256) {
            return Err(BridgeError::invalid(
                "The cancellation hash binding is malformed.",
            ));
        }
        if self.reason.is_empty()
            || self.reason.len() > MAX_CANCEL_REASON_BYTES
            || self.reason.trim() != self.reason
        {
            return Err(BridgeError::invalid(
                "The cancellation reason is malformed.",
            ));
        }
        canonical_sha256(self)
    }
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|character| character.is_ascii_digit() || matches!(character, b'a'..=b'f'))
}

fn canonical_sha256<T: Serialize>(value: &T) -> Result<String, BridgeError> {
    let canonical_value = serde_json::to_value(value)
        .map_err(|_| BridgeError::invalid("The bridge payload cannot be serialized."))?;
    let canonical_bytes = serde_json::to_vec(&canonical_value)
        .map_err(|_| BridgeError::invalid("The bridge payload cannot be serialized."))?;
    let digest = Sha256::digest(canonical_bytes);
    let mut encoded = String::with_capacity(digest.len() * 2);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in digest {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(encoded)
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
    let request_sha256 = request.validate()?;
    Err(BridgeError::session_required(request_sha256))
}

#[tauri::command]
pub fn desktop_bridge_cancel(request: CancelRequest) -> Result<(), BridgeError> {
    let request_sha256 = request.validate()?;
    Err(BridgeError::cancel_unavailable(Some(request_sha256)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const INVOKE_FIXTURE: &str = include_str!("../../../../contracts/desktop/v1/invoke.valid.json");
    const CANCEL_FIXTURE: &str = include_str!("../../../../contracts/desktop/v1/cancel.valid.json");
    const OVERSIZED_UTF8_CANCEL_FIXTURE: &str =
        include_str!("../../../../contracts/desktop/v1/cancel.utf8-oversized.json");
    const ERROR_FIXTURE: &str = include_str!("../../../../contracts/desktop/v1/error.valid.json");

    fn request() -> BridgeRequest {
        BridgeRequest {
            schema_version: BRIDGE_SCHEMA_VERSION.to_owned(),
            operation: "INVOKE".to_owned(),
            session_handle: "desktop-session-handle-000000000001".to_owned(),
            task_id: Uuid::parse_str("00000000-0000-4000-8000-000000000601").unwrap(),
            run_id: Uuid::parse_str("00000000-0000-4000-8000-000000000602").unwrap(),
            registry_version: "a".repeat(64),
            tool_name: "adapter.reference.ut.acquire".to_owned(),
            tool_version: TOOL_VERSION.to_owned(),
            arguments: json!({"fixture_id": "reference-ut-baseline"}),
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
    fn shared_invoke_fixture_round_trips_with_the_python_hash() {
        let request: BridgeRequest = serde_json::from_str(INVOKE_FIXTURE).unwrap();
        assert_eq!(
            request.validate().unwrap(),
            "6b80c5f4f072a58352eec50c83b33d8fdf9b8d7933d81b544598c03fdf6b817b"
        );
        assert_eq!(
            serde_json::to_value(request).unwrap(),
            serde_json::from_str::<Value>(INVOKE_FIXTURE).unwrap()
        );
    }

    #[test]
    fn shared_cancel_and_error_fixtures_are_exact() {
        let request: CancelRequest = serde_json::from_str(CANCEL_FIXTURE).unwrap();
        assert_eq!(
            request.validate().unwrap(),
            "0a07509deb3aa3920938a23bff93e4353949617eccda5bbd4ceba24f9684fd6e"
        );
        assert_eq!(
            serde_json::to_value(request).unwrap(),
            serde_json::from_str::<Value>(CANCEL_FIXTURE).unwrap()
        );
        let expected: Value = serde_json::from_str(ERROR_FIXTURE).unwrap();
        assert_eq!(
            serde_json::to_value(BridgeError::cancel_unavailable(None)).unwrap(),
            expected
        );
    }

    #[test]
    fn shared_cancel_fixture_rejects_a_reason_over_the_utf8_byte_budget() {
        let request: CancelRequest = serde_json::from_str(OVERSIZED_UTF8_CANCEL_FIXTURE).unwrap();
        assert!(request.reason.chars().count() <= 512);
        assert!(request.reason.len() > 512);
        assert_eq!(
            request.validate().unwrap_err().code,
            "DESKTOP_REQUEST_INVALID"
        );
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
        assert!(error.request_sha256.is_some());
        assert!(!desktop_bridge_status().ready);
    }
}
