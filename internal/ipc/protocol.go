package ipc

import "time"

type Message struct {
	Type     string    `json:"type"`
	Statuses []Status  `json:"statuses,omitempty"`
	Settings *Settings `json:"settings,omitempty"`
	Error    string    `json:"error,omitempty"`
}

type Status struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	Display   string    `json:"display"`
	Error     string    `json:"error,omitempty"`
	UpdatedAt time.Time `json:"updated_at"`
}

type Settings struct {
	RefreshInterval  string `json:"refresh_interval"`
	RotationInterval string `json:"rotation_interval"`
	NumberFormat     string `json:"number_format"`
}
