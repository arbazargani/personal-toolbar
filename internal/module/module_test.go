package module

import (
	"context"
	"testing"
)

type testModule struct{ id string }

func (m testModule) ID() string                                 { return m.id }
func (m testModule) Start(context.Context, chan<- Status) error { return nil }
func (m testModule) Stop() error                                { return nil }

func TestRegistryRejectsDuplicateIDs(t *testing.T) {
	r := NewRegistry()
	if err := r.Register(testModule{"example"}); err != nil {
		t.Fatal(err)
	}
	if err := r.Register(testModule{"example"}); err == nil {
		t.Fatal("expected duplicate registration error")
	}
	if len(r.All()) != 1 {
		t.Fatalf("expected one registered module, got %d", len(r.All()))
	}
}
