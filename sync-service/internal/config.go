package internal

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	KafkaBrokers []string
	Topic        string
	DLQTopic     string
	GroupID      string
	RedisURL     string
	RAGGRPCAddr  string
	HTTPAddress  string
	LockTTL      time.Duration
	Retries      int
	OTELEnabled  bool
	OTLPAddress  string
}

func LoadConfig() Config {
	return Config{
		KafkaBrokers: split(env("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")),
		Topic:        env("KAFKA_DOCUMENT_TOPIC", "rag-document-change"), DLQTopic: env("KAFKA_DOCUMENT_DLQ_TOPIC", "rag-document-dlq"),
		GroupID: env("KAFKA_GROUP_ID", "rag-sync-service"), RedisURL: os.Getenv("REDIS_URL"),
		RAGGRPCAddr: env("RAG_GRPC_ADDR", "rag-service:50051"), HTTPAddress: env("SYNC_HTTP_ADDR", ":8081"),
		LockTTL: time.Duration(envInt("DOCUMENT_LOCK_TTL_SECONDS", 300)) * time.Second, Retries: envInt("KAFKA_PROCESS_RETRIES", 3),
		OTELEnabled: envBool("OTEL_ENABLED", false), OTLPAddress: env("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317"),
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
	parsed, err := strconv.Atoi(os.Getenv(name))
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
func split(value string) []string {
	return strings.FieldsFunc(value, func(r rune) bool { return r == ',' || r == ' ' })
}
