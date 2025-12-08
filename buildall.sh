#!/bin/bash
set -e  # exit if any command fails

pip freeze > requirements.txt

echo "Building ai-connector..."
docker build -t ai-connector .

echo "Building summarizer..."
docker build -t summarizer -f Dockerfile.summarizer .

echo "Building scheduler..."
docker build -t scheduler:latest -f Dockerfile.scheduler .

echo "All images built successfully."

