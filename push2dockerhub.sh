docker tag ai-connector:latest fz96tw/ai-connector:v1
docker tag summarizer:latest fz96tw/summarizer:v1
docker tag llama3.2-1b:latest fz96tw/llama3.2-1b:v1


docker push fz96tw/ai-connector:v1
docker push fz96tw/summarizer:v1
docker push fz96tw/llama3.2-1b:v1