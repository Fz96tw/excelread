from fastapi import FastAPI
import ollama
from datetime import datetime

app = FastAPI()
MODEL_NAME = "llama3.2:1b"


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
                    messages=[{"role": "user", "content": "Hello"}],
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
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response["message"]["content"].replace("\n", "; ").replace("|", "/")
            return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def summarize(self, comments: list[str]) -> str:
        if not comments:
            return "No comments available."

        prompt = (
            "You are a helpful assistant. Summarize the following comments "
            "in one or two short sentences. Only summarize the content; do not add extra information. "
            f"The following is the content you need to summarize:\n{comments}"
        )

        response = ollama.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response["message"]["content"].replace("\n", "; ").replace("|", "/")
        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# Create one global summarizer instance (warm-up runs here)
summarizer = OllamaSummarizer(MODEL_NAME)


@app.post("/summarize")
def summarize(comments: list[str]):
    return {"summary": summarizer.summarize(comments)}

@app.post("/summarize_str")
def summarize(comments: str):
    return {"summary": summarizer.summarize_str(comments)}
