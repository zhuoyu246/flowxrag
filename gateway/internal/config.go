package internal

import (
	"os"
	"strconv"
	"time"
)

// Config contains non-secret operational settings. JWT secrets are injected
// through a Kubernetes Secret or a local .env file, never through a ConfigMap.
type Config struct {
	HTTPAddress     string
	RAGGRPCAddress  string
	RAGHTTPURL      string
	RedisURL        string
	JWTSecret       string
	RequireAuth     bool
	RateLimit       int
	RequestTimeout  time.Duration
	CircuitFailures int
	CircuitReset    time.Duration
	OTELEnabled     bool
	OTLPAddress     string
}

func LoadConfig() Config {
	return Config{
		HTTPAddress:     env("GATEWAY_HTTP_ADDR", ":8080"),
		RAGGRPCAddress:  env("RAG_GRPC_ADDR", "rag-service:50051"),
		RAGHTTPURL:      env("RAG_HTTP_URL", "http://rag-service:8000"),
		RedisURL:        os.Getenv("REDIS_URL"),
		JWTSecret:       os.Getenv("JWT_SECRET_KEY"),
		RequireAuth:     envBool("REQUIRE_AUTH", false),
		RateLimit:       envInt("RATE_LIMIT", 100),
		RequestTimeout:  time.Duration(envInt("GATEWAY_TIMEOUT_SECONDS", 65)) * time.Second,
		CircuitFailures: envInt("CIRCUIT_FAILURES", 5),
		CircuitReset:    time.Duration(envInt("CIRCUIT_RESET_SECONDS", 30)) * time.Second,
		OTELEnabled:     envBool("OTEL_ENABLED", false),
		OTLPAddress:     env("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317"),
	}
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func envBool(name string, fallback bool) bool {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	return err == nil && parsed
}

func envInt(name string, fallback int) int {
	value, err := strconv.Atoi(os.Getenv(name))
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}
