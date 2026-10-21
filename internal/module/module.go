package module

import (
	"context"
	"sync"
	"time"
)

type Status struct {
	ID, Name     string
	Value, Error string
	UpdatedAt    time.Time
}
type Module interface {
	ID() string
	Start(context.Context, chan<- Status) error
	Stop() error
}
type Registry struct {
	mu      sync.RWMutex
	modules map[string]Module
}

func NewRegistry() *Registry { return &Registry{modules: make(map[string]Module)} }
func (r *Registry) Register(m Module) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.modules[m.ID()]; ok {
		return &DuplicateError{m.ID()}
	}
	r.modules[m.ID()] = m
	return nil
}
func (r *Registry) All() []Module {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]Module, 0, len(r.modules))
	for _, m := range r.modules {
		out = append(out, m)
	}
	return out
}

type DuplicateError struct{ ID string }

func (e *DuplicateError) Error() string { return "module already registered: " + e.ID }
