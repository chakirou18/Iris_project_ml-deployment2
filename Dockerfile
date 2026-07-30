FROM python:3.9-slim

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -e .

EXPOSE 5000

ENV FLASK_APP=application.py
ENV PYTHONUNBUFFERED=1

CMD ["python", "application.py"]
