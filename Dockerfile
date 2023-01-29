FROM python:3.11-alpine

WORKDIR /app
COPY ./requirements.txt /app
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
CMD python /app/app.py