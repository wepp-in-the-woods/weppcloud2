
# WEPPcloud WebPush FanOut Notifiction Service

This service provides fan-out WebPush notifications for WEPPcloud, allowing the server to send targeted push messages to subscribed clients (such as browsers) for specific simulation runs. It uses the VAPID (Voluntary Application Server Identification) protocol for authentication, and supports enabling/disabling notifications per simulation run (`run_id`). Clients register a Service Worker to receive messages, and communicate subscription IDs to this service, which then manages subscriptions and broadcasts notifications.


## Run Instructions

```bash
export PATH=$PATH:/usr/local/go/bin
go run ./cmd/server
```

## Generating VAPID keys

```bash
sudo apt update
sudo apt install nodejs npm
npm install web-push -g
web-push generate-vapid-keys --json
```
