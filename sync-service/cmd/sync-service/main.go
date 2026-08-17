package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/example/crag-expert-system/sync-service/internal"
)

func main() {
	cfg := internal.LoadConfig()
	shutdownTelemetry, err := internal.SetupTelemetry(context.Background(), "sync-service", cfg)
	if err != nil {
		slog.Error("telemetry initialization failed", "error", err)
		os.Exit(1)
	}
	defer func() { _ = shutdownTelemetry(context.Background()) }()

	service, err := internal.NewService(cfg)
	if err != nil {
		slog.Error("sync-service initialization failed", "error", err)
		os.Exit(1)
	}
	defer service.Close()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go service.StartHTTP()
	go service.Consume(ctx)
	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := service.Shutdown(shutdownCtx); err != nil {
		slog.Error("graceful shutdown failed", "error", err)
	}
}
