package internal

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync/atomic"
	"time"

	ragpb "github.com/example/crag-expert-system/api/proto/ragpb"
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

type Server struct {
	cfg      Config
	http     *http.Server
	grpcConn *grpc.ClientConn
	rag      ragpb.RagServiceClient
	redis    *redis.Client
	breaker  *CircuitBreaker
	ready    atomic.Bool
	requests *prometheus.CounterVec
	errors   *prometheus.CounterVec
	duration *prometheus.HistogramVec
}

type chatRequest struct {
	Question  string `json:"question" binding:"required"`
	SessionID int64  `json:"session_id"`
}

type source struct {
	Source string  `json:"source,omitempty"`
	Title  string  `json:"title,omitempty"`
	URL    string  `json:"url,omitempty"`
	Type   string  `json:"type,omitempty"`
	Page   int32   `json:"page,omitempty"`
	Score  float64 `json:"score,omitempty"`
}

func NewServer(cfg Config) (*Server, error) {
	conn, err := grpc.NewClient(cfg.RAGGRPCAddress, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	server := &Server{
		cfg: cfg, grpcConn: conn, rag: ragpb.NewRagServiceClient(conn),
		breaker:  NewCircuitBreaker(cfg.CircuitFailures, cfg.CircuitReset),
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "rag_requests_total", Help: "Gateway RAG requests"}, []string{"endpoint", "status"}),
		errors:   prometheus.NewCounterVec(prometheus.CounterOpts{Name: "rag_request_errors_total", Help: "Gateway RAG request errors"}, []string{"code"}),
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "rag_request_duration_seconds", Help: "Gateway request duration"}, []string{"endpoint"}),
	}
	if cfg.RedisURL != "" {
		options, parseErr := redis.ParseURL(cfg.RedisURL)
		if parseErr != nil {
			conn.Close()
			return nil, parseErr
		}
		server.redis = redis.NewClient(options)
	}
	registry := prometheus.NewRegistry()
	registry.MustRegister(server.requests, server.errors, server.duration)
	router := gin.New()
	router.Use(gin.Recovery(), server.traceMiddleware())
	router.GET("/health", server.health)
	router.GET("/ready", server.readyHandler)
	router.GET("/metrics", gin.WrapH(promhttp.HandlerFor(registry, promhttp.HandlerOpts{})))
	router.POST("/chat", server.chat)
	router.POST("/search", server.search)

	target, parseErr := url.Parse(cfg.RAGHTTPURL)
	if parseErr != nil {
		conn.Close()
		return nil, parseErr
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorHandler = func(writer http.ResponseWriter, request *http.Request, proxyErr error) {
		slog.Error("legacy rag http proxy failed", "error", proxyErr)
		writeError(writer, http.StatusBadGateway, "UPSTREAM_UNAVAILABLE", "RAG HTTP service is unavailable")
	}
	// Existing authentication, document, SSE and evaluation routes continue to
	// work through this proxy while new core endpoints use gRPC above.
	router.NoRoute(func(c *gin.Context) { proxy.ServeHTTP(c.Writer, c.Request) })
	server.http = &http.Server{Addr: cfg.HTTPAddress, Handler: router, ReadHeaderTimeout: 10 * time.Second}
	return server, nil
}

func (s *Server) Start() {
	s.ready.Store(true)
	slog.Info("gateway started", "address", s.cfg.HTTPAddress, "rag_grpc", s.cfg.RAGGRPCAddress)
	if err := s.http.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("gateway stopped unexpectedly", "error", err)
	}
}

func (s *Server) Shutdown(ctx context.Context) error {
	s.ready.Store(false)
	if s.redis != nil {
		_ = s.redis.Close()
	}
	return s.http.Shutdown(ctx)
}

func (s *Server) Close() { _ = s.grpcConn.Close() }

func (s *Server) health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "gateway"})
}

func (s *Server) readyHandler(c *gin.Context) {
	if !s.ready.Load() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "not_ready"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	if _, err := s.rag.Health(ctx, &ragpb.HealthRequest{}); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "not_ready", "reason": "rag grpc unavailable"})
		return
	}
	if s.redis != nil && s.redis.Ping(ctx).Err() != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "not_ready", "reason": "redis unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ready"})
}

func (s *Server) chat(c *gin.Context) {
	started := time.Now()
	defer func() { s.duration.WithLabelValues("chat").Observe(time.Since(started).Seconds()) }()
	var request chatRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		s.fail(c, http.StatusBadRequest, "INVALID_REQUEST", err.Error())
		return
	}
	claims, err := s.authenticate(c.GetHeader("Authorization"))
	if err != nil {
		s.fail(c, http.StatusUnauthorized, "UNAUTHORIZED", "invalid or missing JWT")
		return
	}
	if !s.breaker.Allow() {
		s.fail(c, http.StatusServiceUnavailable, "CIRCUIT_OPEN", "RAG service is temporarily unavailable")
		return
	}
	if !s.allowRate(c.Request.Context(), c.ClientIP()) {
		s.fail(c, http.StatusTooManyRequests, "RATE_LIMITED", "request rate exceeds the configured sliding window")
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), s.cfg.RequestTimeout)
	defer cancel()
	ctx = injectTrace(ctx)
	response, err := s.rag.Chat(ctx, &ragpb.ChatRequest{Question: request.Question, SessionId: request.SessionID, UserId: claims.Subject})
	if err != nil {
		s.breaker.Failure()
		s.fail(c, http.StatusBadGateway, "RAG_UNAVAILABLE", "RAG service request failed")
		return
	}
	s.breaker.Success()
	s.requests.WithLabelValues("chat", "ok").Inc()
	sources := make([]source, 0, len(response.Sources))
	for _, item := range response.Sources {
		sources = append(sources, source{Source: item.Source, Title: item.Title, URL: item.Url, Type: item.Type, Page: item.Page, Score: item.Score})
	}
	c.JSON(http.StatusOK, gin.H{"answer": response.Answer, "agent_trace": response.AgentTrace, "trigger_web_fallback": response.TriggerWebFallback, "sources": sources, "reasoning_summary": response.ReasoningSummary, "cached": response.Cached, "duration_ms": response.DurationMs})
}

func (s *Server) search(c *gin.Context) {
	query := c.Query("q")
	if query == "" {
		s.fail(c, http.StatusBadRequest, "INVALID_REQUEST", "q is required")
		return
	}
	response, err := s.rag.Search(injectTrace(c.Request.Context()), &ragpb.SearchRequest{Query: query, TopK: 5})
	if err != nil {
		s.fail(c, http.StatusBadGateway, "RAG_UNAVAILABLE", "RAG search failed")
		return
	}
	c.JSON(http.StatusOK, gin.H{"hits": response.Hits})
}

func (s *Server) fail(c *gin.Context, status int, code, message string) {
	s.requests.WithLabelValues("chat", "error").Inc()
	s.errors.WithLabelValues(code).Inc()
	c.JSON(status, gin.H{"error": gin.H{"code": code, "message": message}, "trace_id": traceID(c.Request.Context())})
}

func (s *Server) authenticate(header string) (jwt.RegisteredClaims, error) {
	if !s.cfg.RequireAuth {
		return jwt.RegisteredClaims{}, nil
	}
	if s.cfg.JWTSecret == "" {
		return jwt.RegisteredClaims{}, errors.New("JWT_SECRET_KEY is required")
	}
	tokenValue := strings.TrimSpace(strings.TrimPrefix(header, "Bearer"))
	claims := jwt.RegisteredClaims{}
	token, err := jwt.ParseWithClaims(tokenValue, &claims, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(s.cfg.JWTSecret), nil
	})
	if err != nil || !token.Valid {
		return jwt.RegisteredClaims{}, errors.New("invalid token")
	}
	return claims, nil
}

const slidingWindowScript = `
local key, now, window, limit, member = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return 1`

func (s *Server) allowRate(ctx context.Context, ip string) bool {
	if s.redis == nil {
		return true
	}
	member := make([]byte, 8)
	_, _ = rand.Read(member)
	result, err := s.redis.Eval(ctx, slidingWindowScript, []string{"rag:rate:" + ip}, time.Now().UnixMilli(), 60_000, s.cfg.RateLimit, hex.EncodeToString(member)).Int()
	return err == nil && result == 1
}

func (s *Server) traceMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := otel.GetTextMapPropagator().Extract(c.Request.Context(), propagation.HeaderCarrier(c.Request.Header))
		ctx, span := otel.Tracer("gateway").Start(ctx, c.Request.Method+" "+c.FullPath())
		defer span.End()
		c.Request = c.Request.WithContext(ctx)
		c.Header("X-Trace-ID", traceID(ctx))
		c.Next()
		if c.Writer.Status() >= 500 {
			span.SetStatus(codes.Error, http.StatusText(c.Writer.Status()))
		}
	}
}

func injectTrace(ctx context.Context) context.Context {
	carrier := propagation.MapCarrier{}
	otel.GetTextMapPropagator().Inject(ctx, carrier)
	values := metadata.New(carrier)
	return metadata.NewOutgoingContext(ctx, values)
}

func traceID(ctx context.Context) string { return trace.SpanContextFromContext(ctx).TraceID().String() }

func writeError(writer http.ResponseWriter, status int, code, message string) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_, _ = writer.Write([]byte(`{"error":{"code":"` + code + `","message":"` + message + `"}}`))
}
