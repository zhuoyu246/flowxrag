package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/example/crag-expert-system/gateway/internal"
)

func main() {
	cfg := internal.LoadConfig()
	shutdownTelemetry, err := internal.SetupTelemetry(context.Background(), "gateway", cfg)
	if err != nil {
		slog.Error("telemetry initialization failed", "error", err)
		os.Exit(1)
	}
	defer func() { _ = shutdownTelemetry(context.Background()) }()

	server, err := internal.NewServer(cfg)
	if err != nil {
		slog.Error("gateway initialization failed", "error", err)
		os.Exit(1)
	}
	defer server.Close()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go server.Start()
	<-ctx.Done()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		slog.Error("gateway graceful shutdown failed", "error", err)
	}
}
