package avalai_credit_info

import "testing"

func TestFormatInteger(t *testing.T) {
	cases := map[float64]string{0: "0", 80000: "80,000", 1234567: "1,234,567", -1200: "-1,200"}
	for input, want := range cases {
		if got := formatInteger(input); got != want {
			t.Errorf("formatInteger(%v) = %q, want %q", input, got, want)
		}
	}
}
