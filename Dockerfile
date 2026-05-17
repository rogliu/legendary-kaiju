# Kaiju Kalshi weather-temp trading bot
#
# SECRETS / .env: NOT baked into this image.
# Provide secrets at runtime via:
#   docker run --env-file .env <image> run --station NYC
# or via individual -e flags / EC2 instance profile / SSM Parameter Store.
# Never add .env to the image or bake KALSHI_KEY_ID / KALSHI_PRIVATE_KEY into the build.
#
# Compatible with: Mac (Docker Desktop) and AWS us-east-1 EC2 (same image, no changes).

FROM python:3.12-slim

# Install the eccodes C library required by cfgrib/herbie-data at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libeccodes0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager used by this project).
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency manifests first for Docker layer-cache efficiency.
# The heavy uv sync layer is only invalidated when deps change, not on kaiju/ edits.
COPY pyproject.toml uv.lock ./

# Sync runtime deps only (no dev extras like pytest/ruff/mypy in the image).
RUN uv sync --no-dev

# Copy the kaiju package (source-only; no tests, no .env, no .git).
COPY kaiju ./kaiju

# Entrypoint: delegate to the runner subcommands.
# Usage examples:
#   docker run --env-file .env <img> run --station NYC
#   docker run --env-file .env <img> settle --station NYC --date 2026-05-16
#   docker run --env-file .env <img> retrain --station NYC
ENTRYPOINT ["uv", "run", "python", "-m", "kaiju.runner"]

# Default: print help (safe to run without secrets).
CMD ["--help"]
