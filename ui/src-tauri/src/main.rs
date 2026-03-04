#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use std::path::PathBuf;
use std::process::Child;
use std::sync::Mutex;

use tauri::Manager;

/// Shared application state accessible from all Tauri commands.
pub struct AppState {
    pub client: reqwest::Client,
    pub base_url: String,
    pub sidecar: Mutex<Option<Child>>,
}

/// Find the Python executable from the project's virtual environment.
/// Tries multiple strategies to locate it.
fn find_python() -> PathBuf {
    // 1. Environment variable override (highest priority)
    if let Ok(p) = std::env::var("HOMEBUYER_PYTHON") {
        let path = PathBuf::from(&p);
        if path.exists() {
            println!("Using HOMEBUYER_PYTHON: {:?}", path);
            return path;
        }
    }

    // 2. Try common relative paths from the binary or working directory.
    //    In dev mode, CWD is typically the project root or ui/src-tauri/.
    //    The .venv lives at the HomeBuyer project root.
    let candidate_roots = vec![
        // CWD is project root (e.g., /Users/.../HomeBuyer)
        std::env::current_dir().unwrap_or_default(),
        // CWD is ui/src-tauri/ → go up two levels
        std::env::current_dir()
            .unwrap_or_default()
            .join("../.."),
        // Absolute fallback path
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."),
    ];

    for root in &candidate_roots {
        let venv_python = root.join(".venv/bin/python");
        if venv_python.exists() {
            // IMPORTANT: Do NOT canonicalize — we need the symlink path
            // so that Python recognizes it's running inside the venv
            // and can find the venv's site-packages.
            println!("Found venv Python: {:?}", venv_python);
            return venv_python;
        }
    }

    // 3. Fallback to system python3
    println!("Warning: Could not find project .venv, falling back to system python3");
    PathBuf::from("python3")
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|_app| {
            let python = find_python();
            println!("Using Python: {:?}", python);

            // Spawn the FastAPI sidecar
            let child = std::process::Command::new(&python)
                .args([
                    "-m", "uvicorn", "homebuyer.api:app",
                    "--host", "127.0.0.1",
                    "--port", "8787",
                ])
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .spawn();

            let sidecar = match child {
                Ok(child) => {
                    println!("FastAPI sidecar started (PID: {})", child.id());
                    Some(child)
                }
                Err(e) => {
                    eprintln!("Failed to start FastAPI sidecar: {}", e);
                    None
                }
            };

            // Wait for the sidecar to become ready
            let client = reqwest::Client::new();
            let base_url = "http://127.0.0.1:8787".to_string();

            if sidecar.is_some() {
                let health_url = format!("{}/api/health", &base_url);
                let rt = tokio::runtime::Runtime::new().unwrap();
                let ready = rt.block_on(async {
                    for attempt in 0..30 {
                        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
                        if let Ok(resp) = reqwest::get(&health_url).await {
                            if resp.status().is_success() {
                                println!("Sidecar ready after {} attempts", attempt + 1);
                                return true;
                            }
                        }
                    }
                    false
                });

                if !ready {
                    eprintln!("Warning: FastAPI sidecar did not become ready within 15 seconds");
                }
            }

            _app.manage(AppState {
                client,
                base_url,
                sidecar: Mutex::new(sidecar),
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::health,
            commands::get_status,
            commands::predict_listing,
            commands::predict_manual,
            commands::predict_map_click,
            commands::get_neighborhoods,
            commands::get_neighborhood_detail,
            commands::get_neighborhood_geojson,
            commands::get_market_trend,
            commands::get_market_summary,
            commands::get_model_info,
            commands::get_affordability,
            commands::get_comparables,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            // Kill the sidecar process on exit
            if let Some(state) = app_handle.try_state::<AppState>() {
                if let Ok(mut guard) = state.sidecar.lock() {
                    if let Some(ref mut child) = *guard {
                        println!("Killing FastAPI sidecar (PID: {})", child.id());
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}
