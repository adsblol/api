FROM python:3.11-slim

WORKDIR /app
COPY ./requirements.txt /app
# "Installing this module requires OpenSSL python bindings"
RUN BUILD_DEPS="libssl-dev cargo gcc" && \
    apt-get update && apt-get install -y $BUILD_DEPS && \
    PYOPENSSL=$(grep 'pyopenssl=' requirements.txt) && \
    pip install --no-cache-dir $PYOPENSSL && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    apt-get purge -y --auto-remove $BUILD_DEPS && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . /app
CMD uvicorn app:app --host 0.0.0.0 --port 80

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
