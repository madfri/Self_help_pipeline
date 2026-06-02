# Part 2: Multi-stage Dockerfile for the C++ Business Logic Decoder Server
# =======================================================================
# This Dockerfile builds a minimal C++ binary that runs an embedded HTTP
# server on 127.0.0.1:8080 using cpp-httplib (header-only) and nlohmann/json
# (header-only).

# ---------------------------------------------------------------------------
# STAGE 1: Build Environment
# ---------------------------------------------------------------------------
FROM alpine:3.19 AS builder

# Install build toolchain
RUN apk add --no-cache \
    g++ \
    make \
    cmake \
    wget

# Download cpp-httplib v0.15.3 (single-header, production-grade embedded HTTP server)
RUN mkdir -p /opt/deps && \
    wget -q -O /opt/deps/httplib.h \
    "https://raw.githubusercontent.com/yhirose/cpp-httplib/v0.15.3/httplib.h"

# Download nlohmann/json v3.11.3 (single-header JSON library)
RUN mkdir -p /opt/deps/nlohmann && \
    wget -q -O /opt/deps/nlohmann/json.hpp \
    "https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp"

WORKDIR /build

# Copy source code
COPY src/main.cpp ./

# Compile the binary with static linking for a minimal runtime image.
# Note: We link pthread statically via the linker flag to avoid dynamic deps.
RUN g++ -std=c++17 -O3 -static -pthread \
    -I/opt/deps \
    main.cpp \
    -o decoder_server \
    -Wl,--whole-archive -lpthread -Wl,--no-whole-archive

# Verify the binary is statically linked
RUN echo "=== Verifying static linkage ===" && \
    (ldd decoder_server 2>/dev/null && echo "WARNING: Binary is NOT fully static") || \
    echo "OK: Binary is statically linked."

# ---------------------------------------------------------------------------
# STAGE 2: Runtime Environment
# ---------------------------------------------------------------------------
FROM scratch

# Security: run as non-root (uid 65534 = nobody)
USER 65534:65534

# Copy the statically linked binary from the builder stage
COPY --from=builder /build/decoder_server /decoder_server

# The decoder listens on 127.0.0.1:8080 inside the Pod.
# In Kubernetes, this port is bound to localhost within the Pod network namespace.
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD ["/decoder_server", "--healthcheck"] || exit 1

ENTRYPOINT ["/decoder_server"]
