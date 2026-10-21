package avalai_credit_info

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/example/modular-ubuntu-toolbar/internal/config"
	"github.com/example/modular-ubuntu-toolbar/internal/module"
)

type Service struct {
	store     *config.Store
	client    Client
	refresh   time.Duration
	mu        sync.Mutex
	running   bool
	cancel    context.CancelFunc
	profileMu sync.Map
}

func NewService(store *config.Store, timeout, refresh time.Duration) *Service {
	return &Service{store: store, client: Client{HTTP: &http.Client{Timeout: timeout}, Endpoint: "https://api.avalai.ir/user/v1/credit"}, refresh: refresh}
}
func (s *Service) ID() string { return "avalai_credit_info" }
func (s *Service) Start(ctx context.Context, out chan<- module.Status) error {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return fmt.Errorf("%s is already running", s.ID())
	}
	runCtx, cancel := context.WithCancel(ctx)
	s.cancel = cancel
	s.running = true
	s.mu.Unlock()
	go s.loop(runCtx, out)
	return nil
}
func (s *Service) Stop() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cancel != nil {
		s.cancel()
	}
	s.running = false
	return nil
}
func (s *Service) loop(ctx context.Context, out chan<- module.Status) {
	s.refreshAll(ctx, out)
	ticker := time.NewTicker(s.refresh)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.refreshAll(ctx, out)
		}
	}
}
func (s *Service) refreshAll(ctx context.Context, out chan<- module.Status) {
	profiles, err := s.store.Profiles(ctx)
	if err != nil {
		return
	}
	for _, p := range profiles {
		if !p.Enabled || p.ModuleID != s.ID() {
			continue
		}
		go s.refreshOne(ctx, p, out)
	}
}
func (s *Service) refreshOne(parent context.Context, p config.Profile, out chan<- module.Status) {
	lockValue, _ := s.profileMu.LoadOrStore(p.ID, &sync.Mutex{})
	lock := lockValue.(*sync.Mutex)
	if !lock.TryLock() {
		return
	}
	defer lock.Unlock()
	ctx, cancel := context.WithTimeout(parent, s.client.HTTP.Timeout)
	defer cancel()
	credit, err := s.client.Fetch(ctx, p.APIKey)
	now := time.Now().UTC()
	status := module.Status{ID: p.ID, Name: p.Name, UpdatedAt: now}
	if err != nil {
		_ = s.store.RecordResult(context.Background(), p.ID, nil, now, err)
		status.Error = err.Error()
	} else {
		status.Value = fmt.Sprintf("Units: %.4f | Exchange: %s", credit.RemainingUnit, formatInteger(credit.ExchangeRate))
		statusJSON, _ := json.Marshal(credit)
		_ = s.store.RecordResult(context.Background(), p.ID, statusJSON, now, nil)
	}
	select {
	case out <- status:
	case <-parent.Done():
	}
}
func formatInteger(value float64) string {
	raw := strconv.FormatFloat(value, 'f', 0, 64)
	start := 0
	if strings.HasPrefix(raw, "-") {
		start = 1
	}
	for i := len(raw) - 3; i > start; i -= 3 {
		raw = raw[:i] + "," + raw[i:]
	}
	return raw
}
