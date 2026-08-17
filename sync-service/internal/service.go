package internal

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	ragpb "github.com/example/crag-expert-system/api/proto/ragpb"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"github.com/segmentio/kafka-go"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/propagation"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type Service struct {
	cfg      Config
	reader   *kafka.Reader
	writer   *kafka.Writer
	redis    *redis.Client
	grpcConn *grpc.ClientConn
	rag      ragpb.RagServiceClient
	http     *http.Server
	ready    atomic.Bool
	messages *prometheus.CounterVec
	lag      prometheus.Gauge
	duration prometheus.Histogram
}

func NewService(cfg Config) (*Service, error) {
	if len(cfg.KafkaBrokers) == 0 {
		return nil, errors.New("KAFKA_BOOTSTRAP_SERVERS is required")
	}
	conn, err := grpc.NewClient(cfg.RAGGRPCAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	service := &Service{
		cfg: cfg, grpcConn: conn, rag: ragpb.NewRagServiceClient(conn),
		reader:   kafka.NewReader(kafka.ReaderConfig{Brokers: cfg.KafkaBrokers, GroupID: cfg.GroupID, Topic: cfg.Topic, CommitInterval: 0, MinBytes: 1, MaxBytes: 10e6, MaxWait: time.Second}),
		writer:   &kafka.Writer{Addr: kafka.TCP(cfg.KafkaBrokers...), Topic: cfg.DLQTopic, RequiredAcks: kafka.RequireAll, Balancer: &kafka.Hash{}},
		messages: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "kafka_messages_total", Help: "Kafka sync messages"}, []string{"outcome"}),
		lag:      prometheus.NewGauge(prometheus.GaugeOpts{Name: "kafka_consumer_lag", Help: "Approximate lag of the fetched partition"}),
		duration: prometheus.NewHistogram(prometheus.HistogramOpts{Name: "kafka_message_processing_seconds", Help: "Kafka document processing time"}),
	}
	if cfg.RedisURL == "" {
		conn.Close()
		return nil, errors.New("REDIS_URL is required for document locks")
	}
	options, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		conn.Close()
		return nil, err
	}
	service.redis = redis.NewClient(options)

	registry := prometheus.NewRegistry()
	registry.MustRegister(service.messages, service.lag, service.duration)
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.HandlerFor(registry, promhttp.HandlerOpts{}))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, `{"status":"ok","service":"sync-service"}`)
	})
	mux.HandleFunc("/ready", service.readyHandler)
	service.http = &http.Server{Addr: cfg.HTTPAddress, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	return service, nil
}

func (s *Service) StartHTTP() {
	slog.Info("sync health endpoint started", "address", s.cfg.HTTPAddress)
	if err := s.http.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("sync http stopped unexpectedly", "error", err)
	}
}

func (s *Service) readyHandler(writer http.ResponseWriter, request *http.Request) {
	if !s.ready.Load() {
		writeJSON(writer, http.StatusServiceUnavailable, `{"status":"not_ready"}`)
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	if err := s.redis.Ping(ctx).Err(); err != nil {
		writeJSON(writer, http.StatusServiceUnavailable, `{"status":"not_ready","reason":"redis"}`)
		return
	}
	if _, err := s.rag.Health(ctx, &ragpb.HealthRequest{}); err != nil {
		writeJSON(writer, http.StatusServiceUnavailable, `{"status":"not_ready","reason":"rag"}`)
		return
	}
	writeJSON(writer, http.StatusOK, `{"status":"ready"}`)
}

func (s *Service) Consume(ctx context.Context) {
	s.ready.Store(true)
	slog.Info("kafka consumer started", "topic", s.cfg.Topic, "group", s.cfg.GroupID)
	for {
		message, err := s.reader.FetchMessage(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			slog.Error("kafka fetch failed", "error", err)
			time.Sleep(time.Second)
			continue
		}
		if message.HighWaterMark > message.Offset {
			s.lag.Set(float64(message.HighWaterMark - message.Offset - 1))
		}
		started := time.Now()
		err = s.handleWithRetry(ctx, message)
		s.duration.Observe(time.Since(started).Seconds())
		if errors.Is(err, ErrMessageIgnored) {
			s.messages.WithLabelValues("ignored").Inc()
		} else if err != nil {
			// A message is committed only after it is durably transferred to the DLQ.
			if dlqErr := s.sendDLQ(ctx, message, err); dlqErr != nil {
				slog.Error("dlq publication failed; offset is intentionally not committed", "error", dlqErr)
				continue
			}
			s.messages.WithLabelValues("dlq").Inc()
		} else {
			s.messages.WithLabelValues("success").Inc()
		}
		if err := s.reader.CommitMessages(ctx, message); err != nil {
			slog.Error("offset commit failed", "error", err)
		}
	}
}

func (s *Service) handleWithRetry(ctx context.Context, message kafka.Message) error {
	var lastErr error
	for attempt := 1; attempt <= s.cfg.Retries; attempt++ {
		if err := s.process(ctx, message); err == nil {
			return nil
		} else if errors.Is(err, ErrMessageIgnored) {
			return err
		} else {
			lastErr = err
			slog.Warn("document sync attempt failed", "attempt", attempt, "error", err)
		}
		if attempt < s.cfg.Retries {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(time.Duration(attempt) * time.Second):
			}
		}
	}
	return lastErr
}

func (s *Service) process(ctx context.Context, message kafka.Message) error {
	changes, err := decodeDocumentChanges(message.Value)
	if err != nil {
		return err
	}
	carrier := propagation.MapCarrier{}
	for _, header := range message.Headers {
		carrier[header.Key] = string(header.Value)
	}
	ctx = otel.GetTextMapPropagator().Extract(ctx, carrier)
	ctx, span := otel.Tracer("sync-service").Start(ctx, "kafka document change")
	defer span.End()
	span.SetAttributes(attribute.Int("document.change_count", len(changes)))
	for _, change := range changes {
		if err := s.syncDocument(ctx, change); err != nil {
			return err
		}
	}
	return nil
}

func (s *Service) syncDocument(ctx context.Context, change DocumentChange) error {
	_, span := otel.Tracer("sync-service").Start(ctx, "index document")
	defer span.End()
	span.SetAttributes(attribute.String("document.id", change.DocumentID), attribute.String("document.operation", change.Operation))
	lock, err := s.acquireDocumentLock(ctx, change.DocumentID)
	if err != nil {
		return err
	}
	defer func() {
		if releaseErr := lock.Release(ctx); releaseErr != nil {
			slog.Error("document lock release failed", "error", releaseErr)
		}
	}()
	callCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	response, err := s.rag.IndexDocument(callCtx, &ragpb.IndexDocumentRequest{DocumentId: change.DocumentID, Operation: change.Operation, Source: change.Source, FilePath: change.FilePath})
	if err != nil {
		return fmt.Errorf("rag index RPC: %w", err)
	}
	if !response.Success {
		return errors.New(response.Message)
	}
	return nil
}

func (s *Service) sendDLQ(ctx context.Context, message kafka.Message, cause error) error {
	payload := map[string]interface{}{"error": cause.Error(), "original_topic": s.cfg.Topic, "original_partition": message.Partition, "original_offset": message.Offset, "payload": json.RawMessage(message.Value), "failed_at": time.Now().UTC().Format(time.RFC3339)}
	value, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return s.writer.WriteMessages(ctx, kafka.Message{Key: message.Key, Value: value, Headers: message.Headers})
}

func (s *Service) Shutdown(ctx context.Context) error {
	s.ready.Store(false)
	s.reader.Close()
	s.writer.Close()
	return s.http.Shutdown(ctx)
}

func (s *Service) Close() { _ = s.grpcConn.Close(); _ = s.redis.Close() }

func writeJSON(writer http.ResponseWriter, status int, body string) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_, _ = writer.Write([]byte(body))
}

func traceHeaders(ctx context.Context) []kafka.Header {
	carrier := propagation.MapCarrier{}
	otel.GetTextMapPropagator().Inject(ctx, carrier)
	headers := make([]kafka.Header, 0, len(carrier))
	for key, value := range carrier {
		headers = append(headers, kafka.Header{Key: key, Value: []byte(value)})
	}
	return headers
}

func brokerList(brokers []string) string { return strings.Join(brokers, ",") }
