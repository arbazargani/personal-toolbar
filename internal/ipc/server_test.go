package ipc

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestServerRoundTripAndPermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "toolbar.sock")
	s, err := Listen(path)
	if err != nil {
		if errors.Is(err, os.ErrPermission) || errors.Is(err, os.ErrNotExist) {
			t.Skipf("Unix sockets unavailable in this environment: %v", err)
		}
		t.Fatal(err)
	}
	defer s.Close()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("socket permissions = %o", info.Mode().Perm())
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = s.Serve(ctx, func(m Message) Message { return Message{Type: m.Type} }) }()
	conn, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if err := json.NewEncoder(conn).Encode(Message{Type: "snapshot"}); err != nil {
		t.Fatal(err)
	}
	var response Message
	if err := json.NewDecoder(conn).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response.Type != "snapshot" {
		t.Fatalf("response type = %q", response.Type)
	}
	cancel()
	_ = s.Close()
	time.Sleep(10 * time.Millisecond)
}
