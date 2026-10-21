package ipc

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
)

type Server struct {
	path     string
	listener net.Listener
}

func Listen(path string) (*Server, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	_ = os.Remove(path)
	l, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err = os.Chmod(path, 0600); err != nil {
		l.Close()
		return nil, err
	}
	return &Server{path: path, listener: l}, nil
}
func (s *Server) Serve(ctx context.Context, handler func(Message) Message) error {
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return nil
			default:
				return err
			}
		}
		go func() {
			defer conn.Close()
			req := Message{}
			if err := json.NewDecoder(bufio.NewReader(conn)).Decode(&req); err != nil {
				return
			}
			_ = json.NewEncoder(conn).Encode(handler(req))
		}()
	}
}
func (s *Server) Close() error {
	if s.listener == nil {
		return errors.New("IPC server is not running")
	}
	err := s.listener.Close()
	_ = os.Remove(s.path)
	return err
}
