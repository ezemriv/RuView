# WiFi-DensePose Sensing Server + Telegram Alerts
# Multi-stage build: Rust binary + Python alerter via uv

# Stage 1: Build Rust sensing server
FROM rust:1.85-bookworm AS builder

WORKDIR /build

COPY rust-port/wifi-densepose-rs/Cargo.toml rust-port/wifi-densepose-rs/Cargo.lock ./
COPY rust-port/wifi-densepose-rs/crates/ ./crates/
COPY vendor/ruvector/ /build/vendor/ruvector/

RUN cargo build --release -p wifi-densepose-sensing-server 2>&1 \
    && strip target/release/sensing-server

# Stage 2: Runtime with Python (uv) for Telegram alerts
FROM debian:bookworm-slim

# Install Python via uv (single-layer, no apt python needed)
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python via uv — pinned, reproducible
RUN uv python install 3.12

WORKDIR /app

# Copy Rust binary
COPY --from=builder /build/target/release/sensing-server /app/sensing-server

# Copy UI assets
COPY ui/ /app/ui/

# Copy scripts
COPY scripts/telegram_alert.py /app/scripts/telegram_alert.py
COPY scripts/start.sh /app/scripts/start.sh
COPY scripts/start_esp32.sh /app/scripts/start_esp32.sh
RUN chmod +x /app/scripts/start.sh /app/scripts/start_esp32.sh

# HTTP API
EXPOSE 3000
# WebSocket
EXPOSE 3001
# ESP32 UDP
EXPOSE 5005/udp

ENV RUST_LOG=info
ENV PYTHONUNBUFFERED=1

# Default: simulation mode with Telegram alerts
CMD ["/app/scripts/start.sh"]
