# =============================================================================
# Stage 1: Build Vue UI
# =============================================================================
FROM node:20-slim AS ui-builder

WORKDIR /ui

# Copy UI source
COPY ui/package*.json ./
RUN npm install

COPY ui/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python API + Static Files
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    findutils \
    postgresql-client \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
RUN pip install uv

# Copy and install Python dependencies
COPY api/requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY api/app.py .

# Copy built Vue app from ui-builder stage
COPY --from=ui-builder /ui/dist ./static

# Expose port
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
