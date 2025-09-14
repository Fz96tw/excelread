FROM python:3.11-slim

WORKDIR /appnew
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Install tzdata and set timezone
RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/America/New_York /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Optional: set environment variable
ENV TZ=America/New_York

# Set default Summarizer host for container
ENV SUMMARIZER_HOST=http://summarizer:8000

EXPOSE 5000
CMD ["python", "appnew.py"]
