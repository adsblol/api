FROM python:3.11-alpine

WORKDIR /app
COPY ./requirements.txt /app
# "Installing this module requires OpenSSL python bindings"
RUN apk add --virtual=.build-deps gcc musl-dev libffi-dev openssl-dev python3-dev gcc openldap-dev && \
    PYOPENSSL=$(grep 'pyopenssl=' requirements.txt) && \
    pip install --no-cache-dir $PYOPENSSL && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    apk del .build-deps

COPY . /app
CMD python /app/app.py
ENV PYTHONUNBUFFERED=1
