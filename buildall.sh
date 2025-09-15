#!/bin/bash
set -e  # exit if any command fails

echo "Building ai-connector..."
docker build -t ai-connector .

echo "Building summarizer..."
docker build -t summarizer -f Dockerfile.summarizer .

echo "All images built successfully."

