FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install ALL Chromium system deps manually (bypass playwright --with-deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget ca-certificates gnupg \
    # Core Chromium runtime
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxext6 libx11-6 \
    libxcb1 libxcursor1 libxi6 libxtst6 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libcairo-gobject2 \
    libatspi2.0-0 \
    libwayland-client0 \
    libglib2.0-0 \
    # Fonts that actually exist in trixie
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-unifont \
    fontconfig \
    # Misc
    xdg-utils \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium WITHOUT --with-deps (we installed deps above)
RUN playwright install chromium

# Copy app source
COPY . .

# Non-root user
RUN useradd -m -u 1001 scraper && chown -R scraper:scraper /app /ms-playwright
USER scraper

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info
