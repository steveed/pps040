FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends xdms build-essential git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
# Pinned: the tests depend on Unicorn's behaviour (see src/ppi2000mem.asm).
RUN pip install --no-cache-dir amitools==0.8.1 capstone==5.0.9 unicorn==2.1.4 pytest==9.1.1
# vasm (m68k, Motorola syntax). Only a "latest" archive is published, so the
# build prints the version it got.
RUN curl -sSL http://sun.hasenbraten.de/vasm/release/vasm.tar.gz | tar xz -C /tmp \
 && make -C /tmp/vasm CPU=m68k SYNTAX=mot \
 && cp /tmp/vasm/vasmm68k_mot /tmp/vasm/vobjdump /usr/local/bin/ \
 && rm -rf /tmp/vasm \
 && vasmm68k_mot -v 2>&1 | head -2
WORKDIR /work
