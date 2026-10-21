package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"

	"github.com/example/modular-ubuntu-toolbar/internal/config"
	"github.com/example/modular-ubuntu-toolbar/internal/ipc"
	"github.com/example/modular-ubuntu-toolbar/internal/module"
	"github.com/example/modular-ubuntu-toolbar/modules/avalai_credit_info"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dir, err := os.UserConfigDir()
	if err != nil {
		log.Fatal(err)
	}
	store, err := config.Open(filepath.Join(dir, "modular-toolbar", "toolbar.db"))
	if err != nil {
		log.Fatal(err)
	}
	defer store.Close()
	settings, err := store.Settings(ctx)
	if err != nil {
		log.Fatal(err)
	}

	runtimeDir := os.Getenv("XDG_RUNTIME_DIR")
	if runtimeDir == "" {
		runtimeDir = filepath.Join(os.TempDir(), "modular-toolbar-"+os.Getenv("USER"))
		if err := os.MkdirAll(runtimeDir, 0700); err != nil {
			log.Fatal(err)
		}
	}
	socket, err := ipc.Listen(filepath.Join(runtimeDir, "modular-toolbar.sock"))
	if err != nil {
		log.Fatal(err)
	}
	defer socket.Close()

	registry := module.NewRegistry()
	service := avalai_credit_info.NewService(store, settings.HTTPTimeout, settings.RefreshInterval)
	if err := registry.Register(service); err != nil {
		log.Fatal(err)
	}

	statuses := make(map[string]module.Status)
	var statusesMu sync.RWMutex
	updates := make(chan module.Status, 32)
	for _, m := range registry.All() {
		if err := m.Start(ctx, updates); err != nil {
			log.Fatal(err)
		}
		defer m.Stop()
	}
	go func() {
		for {
			select {
			case status := <-updates:
				statusesMu.Lock()
				statuses[status.ID] = status
				statusesMu.Unlock()
			case <-ctx.Done():
				return
			}
		}
	}()

	go func() {
		err := socket.Serve(ctx, func(request ipc.Message) ipc.Message {
			if request.Type != "snapshot" {
				return ipc.Message{Type: "error", Error: "unsupported request"}
			}
			statusesMu.RLock()
			defer statusesMu.RUnlock()
			response := ipc.Message{Type: "snapshot", Settings: &ipc.Settings{RefreshInterval: settings.RefreshInterval.String(), RotationInterval: settings.RotationInterval.String(), NumberFormat: settings.NumberFormat}}
			for _, status := range statuses {
				response.Statuses = append(response.Statuses, ipc.Status{ID: status.ID, Name: status.Name, Display: status.Value, Error: status.Error, UpdatedAt: status.UpdatedAt})
			}
			return response
		})
		if err != nil && ctx.Err() == nil {
			log.Printf("IPC server stopped: %v", err)
			stop()
		}
	}()

	log.Printf("modular toolbar backend running")
	<-ctx.Done()
	log.Printf("modular toolbar backend stopping")
}
