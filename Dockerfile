FROM python:3.11-slim

WORKDIR /appnew
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

#RUN rm ./config/.bar
#RUN rm ./config/files_local.json
#RUN rm ./config/users.json
#RUN rm ./config/users.json.lock

RUN apt-get update && apt-get install -y dos2unix && \
    dos2unix /appnew/config/system.env && \
    apt-get remove -y dos2unix && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
#RUN dos2unix /appnew/config/env.system

RUN sed -i 's/\r$//' /appnew/config/system.env

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

# for appnew when running in gunicorn
ENV AUTH=user_auth

#CMD ["python", "appnew.py", "--auth", "user_auth"]
CMD ["gunicorn", "appnew:app", "--bind", "0.0.0.0:5000", "-w", "4"]
