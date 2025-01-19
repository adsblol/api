FROM python:3.12-slim

WORKDIR /app
COPY ./requirements.txt /app
COPY ./distance /app/distance

# "Installing this module requires OpenSSL python bindings"
RUN BUILD_DEPS="libssl-dev cargo gcc g++ libffi-dev build-essential" && \
    apt-get update && apt-get install -y $BUILD_DEPS && \
    PYOPENSSL=$(grep 'pyopenssl=' requirements.txt) && \
    pip install --no-cache-dir $PYOPENSSL && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    cd /app/distance && g++ -std=c++14 -O3 -o /usr/local/bin/distance distance.cpp && \
    apt-get purge -y --auto-remove $BUILD_DEPS && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . /app
RUN pip install -e .
CMD uvicorn src.adsb_api.app:app --host 0.0.0.0 --port 80

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
