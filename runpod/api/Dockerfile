FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends autossh openssh-client \
	&& rm -rf /var/lib/apt/lists/*

COPY tunnel-entrypoint.sh /usr/local/bin/tunnel-entrypoint
RUN chmod 0755 /usr/local/bin/tunnel-entrypoint

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.json ./

ENV RUNPOD_API_KEY_FILE=/run/secrets/runpod_api_key

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]