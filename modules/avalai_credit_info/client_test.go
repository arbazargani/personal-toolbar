package avalai_credit_info

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestFetchParsesCredit(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer secret" {
			t.Errorf("authorization header missing")
		}
		w.Write([]byte(`{"limit":0,"remaining_irt":800000,"remaining_unit":10,"total_unit":10,"exchange_rate":80000}`))
	}))
	defer s.Close()
	c := Client{HTTP: &http.Client{Timeout: time.Second}, Endpoint: s.URL}
	got, err := c.Fetch(context.Background(), "secret")
	if err != nil || got.RemainingUnit != 10 || got.ExchangeRate != 80000 {
		t.Fatalf("got %#v, %v", got, err)
	}
}
func TestFetchRejectsHTTPError(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "no", 401) }))
	defer s.Close()
	_, err := (Client{HTTP: http.DefaultClient, Endpoint: s.URL}).Fetch(context.Background(), "x")
	if err == nil {
		t.Fatal("expected error")
	}
}
