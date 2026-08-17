"""OpenTelemetry configuration with a no-op local-development default."""
from __future__ import annotations

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)
_configured = False


def configure_telemetry(service_name: str) -> None:
    """Configure one tracer provider once; disabled mode has no side effects."""
    global _configured
    if _configured or not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if settings.otel_exporter.lower() == "otlp":
            endpoint = settings.otel_exporter_otlp_endpoint or "otel-collector:4317"
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        else:
            exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True
        logger.info("otel_enabled", service=service_name, exporter=settings.otel_exporter)
    except ImportError:
        logger.warning("otel_dependencies_missing", service=service_name)


def instrument_fastapi(app) -> None:
    configure_telemetry("rag-service")
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    except ImportError:
        logger.warning("otel_fastapi_instrumentation_missing")


def instrument_grpc_server() -> None:
    configure_telemetry("rag-service")
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorServer

        GrpcAioInstrumentorServer().instrument()
    except ImportError:
        logger.warning("otel_grpc_instrumentation_missing")
