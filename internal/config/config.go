package config

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"
)

type Store struct{ db *sql.DB }

type Settings struct {
	RefreshInterval, RotationInterval, HTTPTimeout time.Duration
	NumberFormat                                   string
}
type Profile struct {
	ID, Name, APIKey, ModuleID string
	Enabled                    bool
	LastSuccess                *time.Time
	LastError                  string
	Latest                     []byte
}

func Open(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	store := &Store{db: db}
	if err = store.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}
func (s *Store) migrate() error {
	_, err := s.db.Exec(`PRAGMA foreign_keys=ON; CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, module_id TEXT NOT NULL, name TEXT NOT NULL, api_key TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, latest_json BLOB, last_success TEXT, last_error TEXT NOT NULL DEFAULT '');`)
	return err
}
func (s *Store) Close() error { return s.db.Close() }
func (s *Store) Settings(ctx context.Context) (Settings, error) {
	out := Settings{RefreshInterval: 5 * time.Minute, RotationInterval: 8 * time.Second, HTTPTimeout: 15 * time.Second, NumberFormat: "%.4f"}
	rows, err := s.db.QueryContext(ctx, "SELECT key,value FROM settings")
	if err != nil {
		return out, err
	}
	defer rows.Close()
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return out, err
		}
		switch k {
		case "refresh_interval":
			d, e := time.ParseDuration(v)
			if e != nil {
				return out, e
			}
			out.RefreshInterval = d
		case "rotation_interval":
			d, e := time.ParseDuration(v)
			if e != nil {
				return out, e
			}
			out.RotationInterval = d
		case "http_timeout":
			d, e := time.ParseDuration(v)
			if e != nil {
				return out, e
			}
			out.HTTPTimeout = d
		case "number_format":
			out.NumberFormat = v
		}
	}
	return out, rows.Err()
}
func (s *Store) SaveSettings(ctx context.Context, v Settings) error {
	if v.RefreshInterval <= 0 || v.RotationInterval <= 0 || v.HTTPTimeout <= 0 {
		return errors.New("intervals and timeout must be positive")
	}
	for k, val := range map[string]string{"refresh_interval": v.RefreshInterval.String(), "rotation_interval": v.RotationInterval.String(), "http_timeout": v.HTTPTimeout.String(), "number_format": v.NumberFormat} {
		if _, err := s.db.ExecContext(ctx, "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", k, val); err != nil {
			return err
		}
	}
	return nil
}
func (s *Store) Profiles(ctx context.Context) ([]Profile, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT id,module_id,name,api_key,enabled,latest_json,last_success,last_error FROM profiles ORDER BY name")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Profile
	for rows.Next() {
		var p Profile
		var enabled int
		var success sql.NullString
		if err := rows.Scan(&p.ID, &p.ModuleID, &p.Name, &p.APIKey, &enabled, &p.Latest, &success, &p.LastError); err != nil {
			return nil, err
		}
		p.Enabled = enabled != 0
		if success.Valid {
			t, e := time.Parse(time.RFC3339Nano, success.String)
			if e == nil {
				p.LastSuccess = &t
			}
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
func (s *Store) SaveProfile(ctx context.Context, p Profile) error {
	if p.ID == "" || p.Name == "" || p.APIKey == "" || p.ModuleID == "" {
		return errors.New("id, module, name and API key are required")
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO profiles(id,module_id,name,api_key,enabled,latest_json,last_success,last_error) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET module_id=excluded.module_id,name=excluded.name,api_key=excluded.api_key,enabled=excluded.enabled`, p.ID, p.ModuleID, p.Name, p.APIKey, p.Enabled, p.Latest, nullableTime(p.LastSuccess), p.LastError)
	return err
}
func nullableTime(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}
func (s *Store) DeleteProfile(ctx context.Context, id string) error {
	if id == "" {
		return fmt.Errorf("profile id is required")
	}
	_, err := s.db.ExecContext(ctx, "DELETE FROM profiles WHERE id=?", id)
	return err
}
func (s *Store) RecordResult(ctx context.Context, id string, latest []byte, success time.Time, problem error) error {
	msg := ""
	if problem != nil {
		msg = problem.Error()
	}
	if problem != nil {
		_, err := s.db.ExecContext(ctx, "UPDATE profiles SET last_error=? WHERE id=?", msg, id)
		return err
	}
	_, err := s.db.ExecContext(ctx, "UPDATE profiles SET latest_json=?,last_success=?,last_error=? WHERE id=?", latest, nullableTime(&success), msg, id)
	return err
}
