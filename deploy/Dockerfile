# Hugging Face Space (Docker SDK) for the QtFetcher Streamlit app. Built from the bundle made by scripts/deploy_hf.py.
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run as uid 1000; the app writes notes.json and the Hémicycle cache under artifacts/
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Public copy: no live Hémicycle calls (1 credit per click), notes on demand capped per day for all visitors.
# FEATHERLESS_API_KEY comes from the Space's secrets, never from this file.
ENV LLM_PROVIDER=featherless \
    FEATHERLESS_MODEL=google/gemma-4-31B-it \
    DEMO_SIREN=834709248 \
    HEMICYCLE_LIVE=0 \
    LIVE_NOTES_PER_DAY=200 \
    TZ=Europe/Paris

EXPOSE 7860
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
