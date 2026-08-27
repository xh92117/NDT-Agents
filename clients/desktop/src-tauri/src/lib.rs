mod bridge;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            bridge::desktop_bridge_status,
            bridge::desktop_bridge_invoke,
            bridge::desktop_bridge_cancel
        ])
        .run(tauri::generate_context!())
        .expect("the NDT desktop runtime failed");
}
