# Tournament server (cr-arena) with the simulator it runs.
#
# Built from the repo root so the server and the Rust simulator in gym/ always
# come from the same commit. Deploy target: Railway (or any Docker host).
#
#   docker build -t cr-arena .
#   docker run -p 8765:8765 -v cr-arena-data:/data cr-arena
#
# Runtime settings (all optional):
#   PORT               port to listen on (Railway sets this; default 8765)
#   CR_ARENA_DATA      ratings + replays directory (default /data -- mount a volume here)
#   CR_MOVE_TIMEOUT    seconds an agent has to answer each tick (default 2.0)

# ---- stage 1: compile the Rust simulator into a Python wheel ----
FROM python:3.12-slim AS build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /src
COPY gym/ gym/
COPY server/ server/
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels ./gym ./server

# ---- stage 2: slim runtime with just the wheels ----
FROM python:3.12-slim

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Ratings (leaderboard.json) and replays live here. Mount a persistent volume at
# /data, otherwise they are lost on every redeploy.
ENV CR_ARENA_DATA=/data \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data
WORKDIR /data

EXPOSE 8765
# Listen on $PORT when the platform provides one (Railway does), else 8765.
CMD ["sh", "-c", "CR_ARENA_BIND=0.0.0.0:${PORT:-8765} exec cr-arena"]
