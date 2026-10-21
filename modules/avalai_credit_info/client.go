package avalai_credit_info

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type Credit struct {
	Limit         float64 `json:"limit"`
	RemainingIRT  float64 `json:"remaining_irt"`
	RemainingUnit float64 `json:"remaining_unit"`
	TotalUnit     float64 `json:"total_unit"`
	ExchangeRate  float64 `json:"exchange_rate"`
}
type Client struct {
	HTTP     *http.Client
	Endpoint string
}

func (c Client) Fetch(ctx context.Context, key string) (Credit, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Endpoint, nil)
	if err != nil {
		return Credit{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+key)
	res, err := c.HTTP.Do(req)
	if err != nil {
		return Credit{}, err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	if err != nil {
		return Credit{}, err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return Credit{}, fmt.Errorf("API returned HTTP %d", res.StatusCode)
	}
	var v Credit
	if err = json.Unmarshal(body, &v); err != nil {
		return Credit{}, fmt.Errorf("invalid credit response: %w", err)
	}
	return v, nil
}
