var ws;

function connect() {
    ws = new WebSocket("ws://localhost:9002/satiate-presbyopia/wepp");
    
    ws.onopen = function() {
        console.log("Connected");
        $("#status").html("Connected") 
        ws.send(JSON.stringify({"type": "init"}));
    };

    ws.onmessage = function(event) {
        var payload = JSON.parse(event.data);
        if(payload.type === "ping") {
            console.log("Received ping from server");
            ws.send(JSON.stringify({"type": "pong"}));
        }
        else if (payload.type === "status") {
            console.log(payload.data);
        }
        // TODO: Handle data from server.
    };

    ws.onclose = function() {
        $("#status").html("Connection Closed") 
        console.log("Connection closed. Reconnecting...");
        setTimeout(connect, 5000);  // Try to reconnect every 5 seconds.
    };
}
