from fastapi import FastAPI
import ollama
import os
from datetime import datetime

app = FastAPI()
MODEL_NAME = "llama3.2:1b"

# used with running in Docker
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

class OllamaSummarizer:
    def __init__(self, model_name=MODEL_NAME):
        self.model_name = model_name
        self._ensure_ready()

    def _ensure_ready(self):
        """Check if the model is already running, otherwise warm it up."""
        try:
            running_models = ollama.ps()

            # Handle both dict and tuple return formats from ollama.ps()
            already_loaded = any(
                (m["model"] if isinstance(m, dict) else m[0]) == self.model_name
                for m in running_models
            )

            if already_loaded:
                print(f"[INFO] {self.model_name} already loaded.")
            else:
                print(f"[INFO] Warming up {self.model_name}...")
                ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": "Hello"}]
#                    host=OLLAMA_HOST
                )
                print(f"[INFO] {self.model_name} warmed up and ready.")
        except Exception as e:
            print(f"[ERROR] Failed to check/warm up model: {e}")


    def summarize_str(self, comments: str) -> str:
            if not comments:
                return "No comments available."

            prompt = (
                "You are a helpful assistant. Summarize the following comments "
                "in one or two short sentences. Only summarize the content; do not add extra information. "
                f"The following is the content you need to summarize:\n{comments}"
            )

            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}]
#                host=OLLAMA_HOST
            )
            summary = response["message"]["content"]
            return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def summarize(self, comments: list[str]) -> str:
        if not comments:
            return "No comments available."

        prompt = (
            f"The following is the content you need to summarize:\n{comments}"
        )

        response = ollama.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response["message"]["content"]
        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# Create one global summarizer instance (warm-up runs here)
local_summarizer = OllamaSummarizer(MODEL_NAME)


@app.post("/summarize_local")
def summarize_local(comments: list[str]):
    return {"summary": local_summarizer.summarize(comments)}

# this isn't used, so delete it at some point
@app.post("/summarize_local_str")
def summarize_local(comments: str):
    return {"summary": local_summarizer.summarize_str(comments)}


from openai import OpenAI
from dotenv import load_dotenv

#app = FastAPI()
MODEL_NAME2 = "gpt-4o-mini"   # you can switch to gpt-4.1, gpt-4o, etc.

# Load environment variables from a .env file if present
# load .env from config folder
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", "env.system")
load_dotenv(dotenv_path=ENV_PATH)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# OpenAI client (picks up OPENAI_API_KEY from env)
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI(api_key=OPENAI_API_KEY)

class OpenAISummarizer:
    def __init__(self, model_name=MODEL_NAME2):
        self.model_name = model_name
        print(f"[INFO] Using OpenAI model: {self.model_name}")

    def _summarize_prompt(self, comments: str) -> str:
        return (
            f"The following is the content you need to summarize:\n{comments}"
        )

    def summarize_str(self, comments: str) -> str:
        if not comments:
            return "No comments available."

        prompt = self._summarize_prompt(comments)
        response = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.choices[0].message.content
        #summary = summary.replace("\n", "; ").replace("|", "/")
        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def summarize(self, comments: list[str]) -> str:
        if not comments:
            return "No comments available."

        # Convert list to a string for summarization
        comments_text = "\n".join(comments)
        prompt = self._summarize_prompt(comments_text)
        response = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.choices[0].message.content
        #summary = summary.replace("\n", "; ").replace("|", "/")
        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# Create one global summarizer instance
openai_summarizer = OpenAISummarizer(MODEL_NAME2)


@app.post("/summarize_openai")
def summarize_openai(comments: list[str]):
    return {"summary": openai_summarizer.summarize(comments)}

# this isn't used, so delete it at some point
@app.post("/summarize_openai_str")
def summarize_openai_str(comments: str):
    return {"summary": openai_summarizer.summarize_str(comments)}

