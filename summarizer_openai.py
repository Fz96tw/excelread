from fastapi import FastAPI
from openai import OpenAI
import os
from datetime import datetime
from dotenv import load_dotenv

app = FastAPI()
MODEL_NAME = "gpt-4o-mini"   # you can switch to gpt-4.1, gpt-4o, etc.

# Load environment variables from a .env file if present
# load .env from config folder
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", ".env")
load_dotenv(dotenv_path=ENV_PATH)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# OpenAI client (picks up OPENAI_API_KEY from env)
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI(api_key=OPENAI_API_KEY)

class OpenAISummarizer:
    def __init__(self, model_name=MODEL_NAME):
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
        summary = summary.replace("\n", "; ").replace("|", "/")
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
        summary = summary.replace("\n", "; ").replace("|", "/")
        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# Create one global summarizer instance
openai_summarizer = OpenAISummarizer(MODEL_NAME)


@app.post("/summarize")
def summarize(comments: list[str]):
    return {"summary": openai_summarizer.summarize(comments)}

@app.post("/summarize_str")
def summarize_str(comments: str):
    return {"summary": openai_summarizer.summarize_str(comments)}
