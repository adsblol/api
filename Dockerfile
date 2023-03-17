FROM python:3.11-slim

WORKDIR /app
COPY ./requirements.txt /app

ENV BUILD_DEPS="libssl-dev cargo gcc g++ libffi-dev"

# "Installing this module requires OpenSSL python bindings"
RUN apt-get update && apt-get install -y $BUILD_DEPS && \
    PYOPENSSL=$(grep 'pyopenssl=' requirements.txt) && \
    pip install --no-cache-dir $PYOPENSSL && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN cd /app/distance && g++ -std=c++14 -o /usr/local/bin/distance distance.cpp && \
    apt-get purge -y --auto-remove $BUILD_DEPS && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

CMD uvicorn app:app --host 0.0.0.0 --port 80

ENV BUILD_DEPS=
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
