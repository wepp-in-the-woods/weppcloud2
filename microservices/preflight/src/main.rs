use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use warp::Filter;
use warp::ws::WebSocket;
use futures::stream::StreamExt; // Using futures crate

async fn handle_connection(
    mut websocket: WebSocket,
    connections: Arc<Mutex<HashMap<String, WebSocket>>>
) {
    if let Some(result) = websocket.next().await {
        match result {
            Ok(msg) => {
                if msg.is_text() || msg.is_binary() {
                    let run_id = msg.to_str().unwrap_or_default().to_string();
                    println!("run_id: {}", &run_id);
                    connections.lock().await.insert(run_id, websocket);
                }
            },
            Err(e) => {
                eprintln!("Error reading message: {:?}", e);
            }
        }
    }
}


#[tokio::main(flavor = "current_thread")]
async fn main() {
    let connections = Arc::new(Mutex::new(HashMap::new()));

let websocket_route = warp::path("socket")
    .and(warp::ws())
    .map({
        let connections = Arc::clone(&connections);
        move |ws: warp::ws::Ws| {
            ws.on_upgrade({
                let connections = Arc::clone(&connections); // Clone connections here
                move |websocket| {
                    // Handle the connection within the async block instead of spawning a new task
                    async {
                        handle_connection(websocket, connections).await;
                    }
                }
            })
        }
    });

let local = tokio::task::LocalSet::new();

local.spawn_local(async {
    warp::serve(websocket_route)
        .run(([127, 0, 0, 1], 3030))
        .await;
});

local.await;

}

