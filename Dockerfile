FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install production dependencies (cached layer — lock file before source)
COPY backend/pyproject.toml backend/uv.lock ./backend/
WORKDIR /app/backend
RUN uv sync --no-dev --frozen

# Copy application source
WORKDIR /app
COPY backend/ ./backend/
COPY frontend/ ./frontend/

WORKDIR /app/backend

ARG BUILD_COMMIT=unknown
RUN echo "$BUILD_COMMIT" > /app/BUILD_COMMIT

# Store SQLite DB on a mounted volume for persistence across restarts
ENV DB_DIR=/data

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
