# SPHEREx – Lance's Lookout: one container serving the API and the web page.
# Runs on Hugging Face Spaces (port 7860) or anywhere Docker runs:
#   docker build -t lances-lookout . && docker run -p 7860:7860 lances-lookout
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    SPHEREX_CACHE_DIR=/tmp/spherex-cache \
    MPLCONFIGDIR=/tmp/matplotlib

# Hugging Face runs containers as user 1000; give it the app folder so frames/ is writable.
RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
USER app

EXPOSE 7860
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
