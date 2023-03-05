FROM python:3.11-alpine

WORKDIR /app
COPY ./requirements.txt /app
# "Installing this module requires OpenSSL python bindings"
RUN apk add --virtual=.build-deps gcc musl-dev libffi-dev openssl-dev python3-dev gcc openldap-dev rust cargo && \
    apk add --virtual=.run-deps libgcc && \
    PYOPENSSL=$(grep 'pyopenssl=' requirements.txt) && \
    pip install --no-cache-dir $PYOPENSSL && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    apk del .build-deps

COPY . /app
CMD uvicorn app:app --host 0.0.0.0 --port 80

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
