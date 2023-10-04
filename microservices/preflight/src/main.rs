use warp::Filter;

#[tokio::main]
async fn main() {
    // Define a warp filter for a WebSocket endpoint
    let websocket_route = warp::path("socket")
        .and(warp::ws())
        .map(|ws: warp::ws::Ws| {
            ws.on_upgrade(|_websocket| {
                // Handle the WebSocket connection here...
                futures::future::ready(())
            })
        });

    // Start the warp server
    warp::serve(websocket_route)
        .run(([127, 0, 0, 1], 3030))
        .await;
}

