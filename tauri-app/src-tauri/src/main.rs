// Prevents a console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

/// Spawn the Python FastAPI server. Returns the child process handle so we
/// can kill it cleanly when the Tauri window is closed.
fn spawn_python_server() -> Option<Child> {
    // In development: server/app.py lives two levels up from src-tauri/
    // In a production bundle, ship a pre-built binary (e.g. PyInstaller).
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let server_path  = format!("{}/../../server/app.py", manifest_dir);

    let child = Command::new("python3")
        .arg(&server_path)
        .spawn();

    match child {
        Ok(c)  => { println!("[SpotiDL] Server started (pid {})", c.id()); Some(c) }
        Err(e) => { eprintln!("[SpotiDL] Could not start server: {e}"); None }
    }
}

/// Poll GET /api/health until it responds (or we give up after ~10 s).
fn wait_for_server(max_secs: u64) -> bool {
    for _ in 0..max_secs {
        if reqwest_like_check() { return true; }
        thread::sleep(Duration::from_secs(1));
    }
    false
}

/// Minimal HTTP check without pulling in reqwest — just try a TCP connect.
fn reqwest_like_check() -> bool {
    use std::net::TcpStream;
    TcpStream::connect("127.0.0.1:8765").is_ok()
}

fn main() {
    let child_handle: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));

    // Spawn the Python backend
    if let Some(child) = spawn_python_server() {
        *child_handle.lock().unwrap() = Some(child);
    }

    // Wait for the server to be ready before showing the window
    if !wait_for_server(10) {
        eprintln!("[SpotiDL] Warning: server did not respond within 10 s");
    }

    let child_for_exit = Arc::clone(&child_handle);

    tauri::Builder::default()
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(mut child) = child_for_exit.lock().unwrap().take() {
                    let _ = child.kill();
                    println!("[SpotiDL] Server stopped.");
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running SpotiDL");
}
