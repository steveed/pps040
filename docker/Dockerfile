FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends xdms build-essential git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
# Pinned: the tests depend on Unicorn's behaviour (see src/ppi2000mem.asm).
RUN pip install --no-cache-dir amitools==0.8.1 capstone==5.0.9 unicorn==2.1.4 pytest==9.1.1
# vasm (m68k, Motorola syntax). Upstream only publishes a "latest" archive and
# its URL has moved before, so this is a pinned copy of the 2.0f release,
# checked against its hash.
RUN curl -fsSL -o /tmp/vasm.tar.gz https://github.com/piersfinlayson/one-rom-build-deps/releases/download/vasm-2.0f/vasm-2.0f.tar.gz \
 && echo "c84b2de1cbb87831795fe64a85c5d9a7002a766e3a7c30b0a2d7d5e99d878f49  /tmp/vasm.tar.gz" | sha256sum -c - \
 && tar xzf /tmp/vasm.tar.gz -C /tmp \
 && rm /tmp/vasm.tar.gz \
 && make -C /tmp/vasm CPU=m68k SYNTAX=mot \
 && cp /tmp/vasm/vasmm68k_mot /tmp/vasm/vobjdump /usr/local/bin/ \
 && rm -rf /tmp/vasm \
 && vasmm68k_mot -v 2>&1 | head -2
WORKDIR /work
