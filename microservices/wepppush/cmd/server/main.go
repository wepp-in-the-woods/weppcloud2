// main.go
//
// WEPPcloud Web Push Fan-out Service (Go)
// --------------------------------------
// Responsibilities:
//   - Expose a small HTTP API to upsert Web Push subscriptions and per-run settings (with TTL).
//   - Consume Redis DB=2 status messages, filter interesting events, and fan out webpush payloads.
//   - Send E2E-encrypted Web Push notifications using VAPID; prune dead subscriptions on 410/404.
//
// Env (typical):
//
//	REDIS_ADDR=127.0.0.1:6379
//	REDIS_PASS=
//	REDIS_DB=3                 # service state (subscriptions)
//	REDIS_DB_TRIGGERS=2        # your producers publish here
//	VAPID_PUBLIC_KEY=...       # Base64URL, unpadded
//	VAPID_PRIVATE_KEY=...      # Base64URL, unpadded
//	VAPID_SUBJECT=mailto:ops@wepp.cloud
//	HTTP_ADDR=:8080
//	PUSH_WORKERS=8
//	TRIGGER_THROTTLE_SEC=8     # min seconds between TRIGGER per (sub,run); 0 disables
//
// Redis persistence: enable AOF (appendonly yes, appendfsync everysec).
//
// API:
//
//	POST   /subscriptions                    -> create/update subscription (returns {id, vapidPublicKey})
//	POST   /subscriptions/{id}/runs          -> enable/disable run notifications with TTL (days)
//	DELETE /subscriptions/{id}               -> remove subscription
//	GET    /healthz                          -> liveness
//	GET    /readyz                           -> readiness
//
// Payload sent to clients:
//
//	{ "run_id": "<awesome_codename>", "type": "COMPLETED"|"EXCEPTION"|"TRIGGER", "ts": 1733962190123 }
//
// Notes:
//   - We maintain per-run enablement on the server for efficient fan-out.
//   - TTLs are timestamps; we clean opportunistically on read/send.
//
// Build:   go mod init wepppush && go get (see imports) && go build
// Run:     go run main.go
package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/SherClockHolmes/webpush-go"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	redis "github.com/redis/go-redis/v9"
)

//
// ---- Types & Wireup ---------------------------------------------------------------------------
//

// Subscription is the persisted shape for a browser PushSubscription.
type Subscription struct {
	ID          string `json:"id"`           // stable hash of endpoint
	Endpoint    string `json:"endpoint"`     // push service endpoint
	P256dh      string `json:"p256dh"`       // client public key (base64url)
	Auth        string `json:"auth"`         // auth secret (base64url)
	CreatedAtMs int64  `json:"created_at"`   // audit
	LastSeenMs  int64  `json:"last_seen_ms"` // audit
}

// PushPayload is the minimal payload we send to clients.
type PushPayload struct {
	RunID   string `json:"run_id"`
	Type    string `json:"type"`              // COMPLETED|EXCEPTION|TRIGGER
	Message string `json:"message,omitempty"` // optional message
	TS      int64  `json:"ts"`                // epoch ms
}

// API shapes
type postSubReq struct {
	Subscription struct {
		Endpoint string `json:"endpoint"`
		Keys     struct {
			P256dh string `json:"p256dh"`
			Auth   string `json:"auth"`
		} `json:"keys"`
	} `json:"subscription"`
	RunID string `json:"run_id"`
}

type (
	postSubResp struct {
		ID             string `json:"id"`
		VAPIDPublicKey string `json:"vapidPublicKey"`
	}

	postRunsReq struct {
		RunID   string `json:"run_id"`
		Enabled bool   `json:"enabled"`
		TTLDays int    `json:"ttl_days"` // ignored if Disabled; default 7 if zero
	}

	getRunResp struct {
		RunID       string `json:"run_id"`
		Enabled     bool   `json:"enabled"`
		ExpiresAtMs int64  `json:"expires_at_ms"`
	}
)

// App holds dependencies.
type App struct {
	cfg        Config
	store      *Store
	push       *Pusher
	trigger    *TriggerConsumer
	httpServer *http.Server
	throttle   *Throttle
	readyOnce  sync.Once
	readyCh    chan struct{}
}

type vapidFile struct {
	PublicKey  string `json:"publicKey"`
	PrivateKey string `json:"privateKey"`
}

// Config from env.
type Config struct {
	RedisAddr          string
	RedisPass          string
	RedisDB            int
	RedisDBTriggers    int
	VAPIDPublicKey     string
	VAPIDPrivateKey    string
	VAPIDSubject       string
	HTTPAddr           string
	PushWorkers        int
	TriggerThrottleSec int
}

//
// ---- Redis Key Helpers ------------------------------------------------------------------------
//

func subKey(id string) string        { return "sub:" + id }        // HASH: endpoint,p256dh,auth,created_at_ms,last_seen_ms
func runSubsKey(runID string) string { return "runsubs:" + runID } // SET of sub_id
func subRunsKey(subID string) string { return "subruns:" + subID } // HASH: run_id -> expires_at_ms

// deriveSubID creates a stable ID from the endpoint URL.
// Using SHA-256 then base64url-encoding keeps it short and opaque.
func deriveSubID(endpoint string) string {
	sum := sha256.Sum256([]byte(endpoint))
	return base64.RawURLEncoding.EncodeToString(sum[:])
}

//
// ---- Store (Redis) ----------------------------------------------------------------------------
//

type Store struct {
	rdb *redis.Client
	ctx context.Context
}

func NewStore(ctx context.Context, cfg Config) *Store {
	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisAddr,
		Password: cfg.RedisPass,
		DB:       cfg.RedisDB,
	})
	return &Store{rdb: rdb, ctx: ctx}
}

func (s *Store) Ping() error {
	return s.rdb.Ping(s.ctx).Err()
}

// UpsertSubscription writes the subscription metadata. Returns computed subID.
func (s *Store) UpsertSubscription(sub *Subscription) (string, error) {
	if sub.Endpoint == "" || sub.P256dh == "" || sub.Auth == "" {
		return "", errors.New("invalid subscription: missing fields")
	}
	id := deriveSubID(sub.Endpoint)
	now := time.Now().UnixMilli()
	sub.ID, sub.LastSeenMs = id, now
	if sub.CreatedAtMs == 0 {
		sub.CreatedAtMs = now
	}
	_, err := s.rdb.HSet(s.ctx, subKey(id), map[string]interface{}{
		"endpoint":      sub.Endpoint,
		"p256dh":        sub.P256dh,
		"auth":          sub.Auth,
		"created_at_ms": sub.CreatedAtMs,
		"last_seen_ms":  sub.LastSeenMs,
	}).Result()
	return id, err
}

// GetSubscription fetches a subscription by id.
func (s *Store) GetSubscription(id string) (*Subscription, error) {
	h, err := s.rdb.HGetAll(s.ctx, subKey(id)).Result()
	if err != nil {
		return nil, err
	}
	if len(h) == 0 {
		return nil, redis.Nil
	}
	sub := &Subscription{
		ID:       id,
		Endpoint: h["endpoint"],
		P256dh:   h["p256dh"],
		Auth:     h["auth"],
	}
	if v, _ := strconv.ParseInt(h["created_at_ms"], 10, 64); v > 0 {
		sub.CreatedAtMs = v
	}
	if v, _ := strconv.ParseInt(h["last_seen_ms"], 10, 64); v > 0 {
		sub.LastSeenMs = v
	}
	return sub, nil
}

// DeleteSubscription removes sub and its mappings.
func (s *Store) DeleteSubscription(id string) error {
	pipe := s.rdb.TxPipeline()
	pipe.Del(s.ctx, subKey(id))
	// Remove sub from all runsubs:* sets.
	// We need to read subruns to know the runs.
	runs, _ := s.rdb.HKeys(s.ctx, subRunsKey(id)).Result()
	for _, run := range runs {
		pipe.SRem(s.ctx, runSubsKey(run), id)
	}
	pipe.Del(s.ctx, subRunsKey(id))
	_, err := pipe.Exec(s.ctx)
	return err
}

// EnableRunForSub sets/renews TTL and adds the reverse index.
func (s *Store) EnableRunForSub(subID, runID string, expiresAtMs int64) error {
	pipe := s.rdb.TxPipeline()
	pipe.HSet(s.ctx, subRunsKey(subID), runID, expiresAtMs)
	pipe.SAdd(s.ctx, runSubsKey(runID), subID)
	_, err := pipe.Exec(s.ctx)
	return err
}

// DisableRunForSub removes the mapping both sides.
func (s *Store) DisableRunForSub(subID, runID string) error {
	pipe := s.rdb.TxPipeline()
	pipe.HDel(s.ctx, subRunsKey(subID), runID)
	pipe.SRem(s.ctx, runSubsKey(runID), subID)
	_, err := pipe.Exec(s.ctx)
	return err
}

// GetSubsForRun returns the candidate subIDs for a run.
func (s *Store) GetSubsForRun(runID string) ([]string, error) {
	return s.rdb.SMembers(s.ctx, runSubsKey(runID)).Result()
}

// GetRunExpiry returns expires_at_ms for (sub, run) or 0 if none.
func (s *Store) GetRunExpiry(subID, runID string) (int64, error) {
	v, err := s.rdb.HGet(s.ctx, subRunsKey(subID), runID).Result()
	if err == redis.Nil {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	ms, _ := strconv.ParseInt(v, 10, 64)
	return ms, nil
}

// CleanupExpiredForSub removes expired runs for a subscription.
func (s *Store) CleanupExpiredForSub(subID string, nowMs int64) error {
	kv, err := s.rdb.HGetAll(s.ctx, subRunsKey(subID)).Result()
	if err != nil {
		return err
	}
	if len(kv) == 0 {
		return nil
	}
	pipe := s.rdb.TxPipeline()
	for run, expStr := range kv {
		exp, _ := strconv.ParseInt(expStr, 10, 64)
		if exp > 0 && exp < nowMs {
			pipe.HDel(s.ctx, subRunsKey(subID), run)
			pipe.SRem(s.ctx, runSubsKey(run), subID)
		}
	}
	_, err = pipe.Exec(s.ctx)
	return err
}

//
// ---- Pusher (webpush-go) ----------------------------------------------------------------------
//

type Pusher struct {
	vapidPublic  string
	vapidPrivate string
	vapidSubj    string
	client       *http.Client
}

func NewPusher(cfg Config) *Pusher {
	return &Pusher{
		vapidPublic:  cfg.VAPIDPublicKey,
		vapidPrivate: cfg.VAPIDPrivateKey,
		vapidSubj:    cfg.VAPIDSubject,
		client: &http.Client{
			Timeout: 15 * time.Second,
		},
	}
}

// Send sends a single push. Returns true if permanently gone (410/404) so caller can prune.
func (p *Pusher) Send(ctx context.Context, sub *Subscription, payload []byte) (gone bool, err error) {
	resp, err := webpush.SendNotificationWithContext(ctx, payload, &webpush.Subscription{
		Endpoint: sub.Endpoint,
		Keys:     webpush.Keys{P256dh: sub.P256dh, Auth: sub.Auth},
	}, &webpush.Options{
		Subscriber:      p.vapidSubj,    // should be "mailto:ops@wepp.cloud" or https URL
		VAPIDPublicKey:  p.vapidPublic,  // base64url, unpadded
		VAPIDPrivateKey: p.vapidPrivate, // matching private
		TTL:             60,
		HTTPClient:      p.client,
	})
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	u, _ := url.Parse(sub.Endpoint)
	aud := ""
	if u != nil {
		aud = u.Scheme + "://" + u.Host
	}

	if resp.StatusCode == http.StatusGone || resp.StatusCode == http.StatusNotFound {
		log.Printf("[push] %d host=%s subID=%s (dead endpoint)", resp.StatusCode, u.Host, sub.ID)
		return true, nil
	}
	if resp.StatusCode >= 400 {
		log.Printf("[push] %d host=%s aud=%s sub=%s subClaim=%s vapidPub=%s... msg=%s",
			resp.StatusCode, u.Host, aud, sub.ID, p.vapidSubj, p.vapidPublic[:8], strings.TrimSpace(string(body)))
		return false, fmt.Errorf("push http %d", resp.StatusCode)
	}

	log.Printf("[push] 2xx host=%s aud=%s sub=%s", u.Host, aud, sub.ID)
	return false, nil
}

//
// ---- Throttle (in-memory) ---------------------------------------------------------------------
//

type Throttle struct {
	window time.Duration
	mu     sync.Mutex
	seen   map[string]time.Time // key: subID|runID|type
}

func NewThrottle(windowSec int) *Throttle {
	if windowSec <= 0 {
		return &Throttle{window: 0}
	}
	return &Throttle{
		window: time.Duration(windowSec) * time.Second,
		seen:   make(map[string]time.Time),
	}
}

func (t *Throttle) Allow(subID, runID, typ string) bool {
	if t.window == 0 {
		return true
	}
	key := subID + "|" + runID + "|" + typ
	now := time.Now()
	t.mu.Lock()
	defer t.mu.Unlock()
	if last, ok := t.seen[key]; ok {
		if now.Sub(last) < t.window {
			return false
		}
	}
	t.seen[key] = now
	return true
}

//
// ---- Trigger Consumer (Redis DB=2) ------------------------------------------------------------
//

type TriggerConsumer struct {
	rdb     *redis.Client
	store   *Store
	push    *Pusher
	workers int
	th      *Throttle
}

func NewTriggerConsumer(cfg Config, store *Store, push *Pusher, th *Throttle) *TriggerConsumer {
	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisAddr,
		Password: cfg.RedisPass,
		DB:       cfg.RedisDBTriggers,
	})
	return &TriggerConsumer{rdb: rdb, store: store, push: push, workers: max(1, cfg.PushWorkers), th: th}
}

// Start begins a PSUBSCRIBE on all channels (*) and filters messages.
// You can narrow the pattern to reduce noise once you finalize channel names.
func (tc *TriggerConsumer) Start(ctx context.Context) error {
	pubsub := tc.rdb.PSubscribe(ctx, "*")
	_, err := pubsub.Receive(ctx)
	if err != nil {
		return fmt.Errorf("pubsub receive: %w", err)
	}

	msgCh := pubsub.Channel()
	// worker pool for pushes
	jobs := make(chan PushPayload, 1024)
	for i := 0; i < tc.workers; i++ {
		go tc.pushWorker(ctx, jobs)
	}

	go func() {
		defer pubsub.Close()
		for {
			select {
			case <-ctx.Done():
				return
			case m, ok := <-msgCh:
				if !ok {
					return
				}
				typ := classifyMessage(m.Payload)
				if typ == "" {
					continue // uninteresting
				}
				runID := parseRunIDFromChannel(m.Channel)
				if runID == "" {
					runID = parseRunIDFromPayload(m.Payload)
				}
				if runID == "" {
					continue
				}

				message := m.Payload
				message = strings.ReplaceAll(message, typ, "")
				message = strings.TrimSpace(message)

				jobs <- PushPayload{
					RunID:   runID,
					Type:    typ,
					Message: message,
					TS:      time.Now().UnixMilli(),
				}
			}
		}
	}()
	return nil
}

func (tc *TriggerConsumer) pushWorker(ctx context.Context, jobs <-chan PushPayload) {
	for {
		select {
		case <-ctx.Done():
			return
		case p := <-jobs:
			tc.fanout(ctx, p)
		}
	}
}

// fanout looks up subs for run, filters TTL, throttles TRIGGER, and sends.
func (tc *TriggerConsumer) fanout(ctx context.Context, p PushPayload) {
	subIDs, err := tc.store.GetSubsForRun(p.RunID)
	if err != nil {
		log.Printf("fanout get subs: %v", err)
		return
	}
	if len(subIDs) == 0 {
		return
	}
	payloadBytes, _ := json.Marshal(p)
	nowMs := time.Now().UnixMilli()

	for _, sid := range subIDs {
		// TTL check (and opportunistic cleanup)
		exp, err := tc.store.GetRunExpiry(sid, p.RunID)
		if err != nil {
			log.Printf("expiry read: %v", err)
			continue
		}
		if exp == 0 || exp < nowMs {
			_ = tc.store.DisableRunForSub(sid, p.RunID)
			continue
		}
		if p.Type == "TRIGGER" && !tc.th.Allow(sid, p.RunID, p.Type) {
			continue
		}
		sub, err := tc.store.GetSubscription(sid)
		if err != nil {
			if err == redis.Nil {
				_ = tc.store.DisableRunForSub(sid, p.RunID)
			}
			continue
		}
		log.Printf("push sub=%s run=%s: %s, push endpoint=%s", sid, p.RunID, p.Type, sub.Endpoint)
		gone, err := tc.push.Send(ctx, sub, payloadBytes)
		if err != nil {
			// Retry policy could be added here (5xx). Keep it simple for MVP.
			log.Printf("push err sub=%s run=%s: %v", sid, p.RunID, err)
			continue
		}
		if gone {
			_ = tc.store.DeleteSubscription(sid)
		}
	}
}

// classifyMessage returns the type if the line contains an interesting verb.
func classifyMessage(line string) string {
	// Simple contains check. Tweak if needed.
	switch {
	case strings.Contains(line, " COMPLETED "):
		return "COMPLETED"
	case strings.Contains(line, " EXCEPTION "):
		return "EXCEPTION"
	default:
		return ""
	}
}

// parseRunIDFromChannel expects "<run_id>:<component>"
func parseRunIDFromChannel(ch string) string {
	if i := strings.IndexByte(ch, ':'); i > 0 {
		return ch[:i]
	}
	return ""
}

// parseRunIDFromPayload falls back to "(<runid>)" pattern used in your messages.
func parseRunIDFromPayload(s string) string {
	// crude extraction of "(<runid>)"
	i := strings.LastIndexByte(s, '(')
	j := strings.LastIndexByte(s, ')')
	if i >= 0 && j > i+1 {
		return s[i+1 : j]
	}
	return ""
}

//
// ---- HTTP API & Handlers ----------------------------------------------------------------------
//

func (a *App) routes() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	// Middleware to strip /weppcloud-microservices/webpush prefix
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			prefix := "/weppcloud-microservices/webpush"
			if strings.HasPrefix(r.URL.Path, prefix) {
				r.URL.Path = strings.TrimPrefix(r.URL.Path, prefix)
				if r.URL.Path == "" {
					r.URL.Path = "/"
				}
			}
			next.ServeHTTP(w, r)
		})
	})

	r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	r.Get("/readyz", func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-a.readyCh:
			w.WriteHeader(http.StatusOK)
		default:
			http.Error(w, "starting", http.StatusServiceUnavailable)
		}
	})

	r.Get("/vapid-public-key", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(a.cfg.VAPIDPublicKey))
	})

	r.Post("/subscriptions", a.handlePostSubscription)
	r.Post("/subscriptions/{id}/runs", a.handlePostRuns)
	r.Get("/subscriptions/{id}/runs/{run_id}", a.handleGetRun)
	r.Delete("/subscriptions/{id}", a.handleDeleteSubscription)

	return r
}

// POST /subscriptions
// Body: { endpoint, keys: { p256dh, auth } }
// Resp: { id, vapidPublicKey }
func (a *App) handlePostSubscription(w http.ResponseWriter, r *http.Request) {
	var req postSubReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}

	sub := &Subscription{
		Endpoint: req.Subscription.Endpoint,
		P256dh:   req.Subscription.Keys.P256dh,
		Auth:     req.Subscription.Keys.Auth,
	}

	id, err := a.store.UpsertSubscription(sub)
	if err != nil {
		// Instead of failing hard, return current subID if already stored
		existingID := deriveSubID(sub.Endpoint)
		resp := postSubResp{ID: existingID, VAPIDPublicKey: a.cfg.VAPIDPublicKey}
		writeJSON(w, http.StatusOK, resp)
		return
	}

	_ = a.store.CleanupExpiredForSub(id, time.Now().UnixMilli())
	resp := postSubResp{ID: id, VAPIDPublicKey: a.cfg.VAPIDPublicKey}
	writeJSON(w, http.StatusOK, resp)
}

// POST /subscriptions/{id}/runs
// Body: { run_id, enabled, ttl_days }
func (a *App) handlePostRuns(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if id == "" {
		http.Error(w, "missing id", http.StatusBadRequest)
		return
	}
	var req postRunsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}
	if req.RunID == "" {
		http.Error(w, "missing run_id", http.StatusBadRequest)
		return
	}
	if req.Enabled {
		ttlDays := req.TTLDays
		if ttlDays <= 0 {
			ttlDays = 7
		}
		exp := time.Now().Add(time.Duration(ttlDays) * 24 * time.Hour).UnixMilli()
		if err := a.store.EnableRunForSub(id, req.RunID, exp); err != nil {
			http.Error(w, "store error", http.StatusInternalServerError)
			return
		}
	} else {
		if err := a.store.DisableRunForSub(id, req.RunID); err != nil {
			http.Error(w, "store error", http.StatusInternalServerError)
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

// GET /subscriptions/{id}/runs/{run_id}
func (a *App) handleGetRun(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	runID := chi.URLParam(r, "run_id")
	if id == "" || runID == "" {
		http.Error(w, "missing id or run_id", http.StatusBadRequest)
		return
	}

	exp, err := a.store.GetRunExpiry(id, runID)
	if err != nil {
		http.Error(w, "store error", http.StatusInternalServerError)
		return
	}

	now := time.Now().UnixMilli()
	resp := getRunResp{
		RunID:       runID,
		Enabled:     exp > now,
		ExpiresAtMs: exp,
	}
	// (Optional) prevent caches from lying
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, resp)
}

// DELETE /subscriptions/{id}
func (a *App) handleDeleteSubscription(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if id == "" {
		http.Error(w, "missing id", http.StatusBadRequest)
		return
	}
	if err := a.store.DeleteSubscription(id); err != nil {
		http.Error(w, "store error", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

//
// ---- Boot -------------------------------------------------------------------------------------
//

func loadConfig() (Config, error) {
	getInt := func(key string, def int) int {
		s := os.Getenv(key)
		if s == "" {
			return def
		}
		i, err := strconv.Atoi(s)
		if err != nil {
			return def
		}
		return i
	}
	// Default to env first
	pub := os.Getenv("VAPID_PUBLIC_KEY")
	priv := os.Getenv("VAPID_PRIVATE_KEY")

	// If env not set, fall back to vapid.json in same dir as binary
	if pub == "" || priv == "" {
		// adjust path as needed (could also getenv("VAPID_JSON_PATH", "vapid.json"))
		vapidPath := "/workdir/weppcloud2/microservices/wepppush/vapid.json"
		if f, err := os.Open(vapidPath); err == nil {
			defer f.Close()
			var vf vapidFile
			if err := json.NewDecoder(f).Decode(&vf); err == nil {
				if pub == "" {
					pub = vf.PublicKey
				}
				if priv == "" {
					priv = vf.PrivateKey
				}
			}
		}
	}

	cfg := Config{
		RedisAddr:          getenv("REDIS_ADDR", "127.0.0.1:6379"),
		RedisPass:          os.Getenv("REDIS_PASS"),
		RedisDB:            getInt("REDIS_DB", 3),
		RedisDBTriggers:    getInt("REDIS_DB_TRIGGERS", 2),
		VAPIDPublicKey:     strings.TrimSpace(pub),
		VAPIDPrivateKey:    strings.TrimSpace(priv),
		VAPIDSubject:       getenv("VAPID_SUBJECT", "https://wc.bearhive.duckdns.org/"),
		HTTPAddr:           getenv("HTTP_ADDR", ":9003"),
		PushWorkers:        getInt("PUSH_WORKERS", 8),
		TriggerThrottleSec: getInt("TRIGGER_THROTTLE_SEC", 8),
	}
	if cfg.VAPIDPublicKey == "" || cfg.VAPIDPrivateKey == "" {
		return cfg, errors.New("missing VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY")
	}

	log.Printf("[boot] vapid.pub prefix=%s len=%d", strings.TrimSpace(cfg.VAPIDPublicKey)[:8], len(strings.TrimSpace(cfg.VAPIDPublicKey)))
	log.Printf("[boot] vapid.sub=%s", cfg.VAPIDSubject)

	return cfg, nil
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	store := NewStore(ctx, cfg)
	if err := store.Ping(); err != nil {
		log.Fatalf("redis ping: %v", err)
	}

	pusher := NewPusher(cfg)
	throttle := NewThrottle(cfg.TriggerThrottleSec)
	consumer := NewTriggerConsumer(cfg, store, pusher, throttle)

	app := &App{
		cfg:     cfg,
		store:   store,
		push:    pusher,
		trigger: consumer,
		readyCh: make(chan struct{}),
	}

	// Start trigger consumer
	if err := consumer.Start(ctx); err != nil {
		log.Fatalf("trigger consumer: %v", err)
	}

	// HTTP server
	mux := app.routes()
	srv := &http.Server{
		Addr:         cfg.HTTPAddr,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 15 * time.Second,
	}
	app.httpServer = srv

	// Mark ready once HTTP listener is up
	go func() {
		app.readyOnce.Do(func() { close(app.readyCh) })
		log.Printf("listening on %s", cfg.HTTPAddr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("http: %v", err)
		}
	}()
	// Block forever (or hook OS signals here if you want graceful shutdowns)
	select {}
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
