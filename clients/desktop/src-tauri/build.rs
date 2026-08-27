fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "desktop_bridge_status",
            "desktop_bridge_invoke",
            "desktop_bridge_cancel",
        ]),
    ))
    .expect("failed to generate the pinned desktop manifest");
}
