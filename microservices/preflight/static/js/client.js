var ws;

function connect() {
    ws = new WebSocket("ws://your_server_address:8888/websocket");
    
    ws.onopen = function() {
        console.log("Connected");
        ws.send(JSON.stringify({"type": "run_id", "data": "your_run_id"}));
    };

    ws.onmessage = function(event) {
        var payload = JSON.parse(event.data);
        if(payload.type === "ping") {
            console.log("Received ping from server");
            ws.send(JSON.stringify({"type": "pong"}));
        }
        // TODO: Handle data from server.
    };

    ws.onclose = function() {
        console.log("Connection closed. Reconnecting...");
        setTimeout(connect, 5000);  // Try to reconnect every 5 seconds.
    };
}

$(document).ready(function() {
    connect();
});

