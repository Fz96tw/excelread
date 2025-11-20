from fastapi import FastAPI
import ollama
import os
from datetime import datetime
from typing import List, Optional
#import openai
from openai import OpenAI


#from openai import OpenAI
from dotenv import load_dotenv

import tiktoken
from datetime import datetime
#from openai.error import OpenAIError

from summarizer_claude import *

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
            return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name}) {summary}"

    
    def summarize(self, comments: list[str], completion_tokens: int = 500) -> str:
        if not comments:
            return "No comments available."

        # Model context limits (approximate tokens for Ollama models)
        # llama3.2:1b has ~128k context, but we'll be conservative
        MODEL_CONTEXT_LIMITS = {
            "llama3.2:1b": 32000,
            "llama3.2:3b": 32000,
            "llama2": 4096,
            "llama2:13b": 4096,
            "mistral": 8192,
        }

        model_limit = MODEL_CONTEXT_LIMITS.get(self.model_name, 4096)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Helper to count tokens (approximate: 1 token ≈ 4 characters for English text)
        def count_tokens(text: str) -> int:
            return len(text) // 4

        # Split comments into chunks
        chunks = []
        chunk_token_counts = []
        current_chunk = []
        current_tokens = 0
        total_tokens = 0

        for comment in comments:
            comment_tokens = count_tokens(comment)
            total_tokens += comment_tokens
            
            if comment_tokens > max_tokens_per_chunk:
                comment = comment[:max_tokens_per_chunk * 4]  # truncate large comment
                comment_tokens = max_tokens_per_chunk

            if current_tokens + comment_tokens > max_tokens_per_chunk:
                chunk_text = "\n".join(current_chunk)
                chunks.append(chunk_text)
                chunk_token_counts.append(current_tokens)
                current_chunk = [comment]
                current_tokens = comment_tokens
            else:
                current_chunk.append(comment)
                current_tokens += comment_tokens

        if current_chunk:
            chunk_text = "\n".join(current_chunk)
            chunks.append(chunk_text)
            chunk_token_counts.append(current_tokens)

        # Print token statistics
        print(f"[INFO] Total tokens across all comments: {total_tokens}")
        print(f"[INFO] Number of chunks: {len(chunks)}")
        for i, token_count in enumerate(chunk_token_counts, 1):
            print(f"[INFO] Chunk {i} tokens: {token_count}")

        # Summarize each chunk
        summaries = []
        for chunk in chunks:
            prompt = f"The following is the content you need to summarize:\n{chunk}"

            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response["message"]["content"])
            except Exception as e:
                print(f"[ERROR] Ollama API error: {e}")
                summaries.append("[Chunk summary failed]")

        # Combine chunk summaries if multiple
        if len(summaries) > 1:
            joined = "\n".join(summaries)
            combined_prompt = f"The following is the content you need to summarize:\n{joined}"
            #combined_prompt = f"The following is the content you need to summarize:\n{'\n'.join(summaries)}"
            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response["message"]["content"]
            except Exception as e:
                print(f"[ERROR] Ollama API error in final summary: {e}")
                final_summary = "[Final summary failed due to API error]"
        else:
            final_summary = summaries[0]

        return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name}) {final_summary}"



    def summarize_old(self, comments: list[str]) -> str:
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
        return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name}) {summary}"


    def summarize_ex(self, comments: List[str], field: Optional[str] = None, completion_tokens: int = 500) -> str:
        if not comments:
            return "No comments available."

        # Model context limits (approximate tokens for Ollama models)
        MODEL_CONTEXT_LIMITS = {
            "llama3.2:1b": 32000,
            "llama3.2:3b": 32000,
            "llama2": 4096,
            "llama2:13b": 4096,
            "mistral": 8192,
        }

        model_limit = MODEL_CONTEXT_LIMITS.get(self.model_name, 4096)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Helper to count tokens (approximate: 1 token ≈ 4 characters for English text)
        def count_tokens(text: str) -> int:
            return len(text) // 4

        # Split comments into chunks
        chunks = []
        chunk_token_counts = []
        current_chunk = []
        current_tokens = 0
        total_tokens = 0

        for comment in comments:
            comment_tokens = count_tokens(comment)
            total_tokens += comment_tokens
            
            if comment_tokens > max_tokens_per_chunk:
                comment = comment[:max_tokens_per_chunk * 4]  # truncate large comment
                comment_tokens = max_tokens_per_chunk

            if current_tokens + comment_tokens > max_tokens_per_chunk:
                chunk_text = "\n".join(current_chunk)
                chunks.append(chunk_text)
                chunk_token_counts.append(current_tokens)
                current_chunk = [comment]
                current_tokens = comment_tokens
            else:
                current_chunk.append(comment)
                current_tokens += comment_tokens

        if current_chunk:
            chunk_text = "\n".join(current_chunk)
            chunks.append(chunk_text)
            chunk_token_counts.append(current_tokens)

        # Print token statistics
        print(f"[INFO] Total tokens across all comments: {total_tokens}")
        print(f"[INFO] Number of chunks: {len(chunks)}")
        for i, token_count in enumerate(chunk_token_counts, 1):
            print(f"[INFO] Chunk {i} tokens: {token_count}")

        # Determine the prompt to use
        if field:
            prompt_template = f"{field}. Here's the text: {{chunk}}"
        else:
            prompt_template = "The following is the content you need to summarize:\n{chunk}"

        # Summarize each chunk
        summaries = []
        for chunk in chunks:
            prompt = prompt_template.format(chunk=chunk)

            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response["message"]["content"])
            except Exception as e:
                print(f"[ERROR] Ollama API error: {e}")
                summaries.append("[Chunk summary failed]")

        # Combine chunk summaries if multiple
        if len(summaries) > 1:
            joined = "\n".join(summaries)
            # Use field prompt or default for final summary
            if field:
                combined_prompt = f"{field}. Here's the text: {joined}"
            else:
                combined_prompt = f"The following is the content you need to summarize:\n{joined}"
            
            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response["message"]["content"]
            except Exception as e:
                print(f"[ERROR] Ollama API error in final summary: {e}")
                final_summary = "[Final summary failed due to API error]"
        else:
            final_summary = summaries[0]

        return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name}) {final_summary}"



    def summarize_ex_old(self, comments: List[str], field: Optional[str] = None) -> str:
        if not comments:
            return "No comments available."

        # Use the field as the prompt if provided
        if field:
            prompt = f"{field}. Here's the text: {comments}"
        else:
            prompt = f"The following is the content you need to summarize:\n{comments}"

        # Call the LLM
        response = ollama.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )

        summary = response["message"]["content"]

        return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# Create one global summarizer instance (warm-up runs here)
local_summarizer = OllamaSummarizer(MODEL_NAME)

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# Define a Pydantic model for the expected JSON payload
class SummarizeRequest(BaseModel):
    comments: List[str]
    field: Optional[str] = None

@app.post("/summarize_local_ex")
def summarize_local_ex(payload: SummarizeRequest):
    comments = payload.comments
    field_arg = payload.field

    print(f"/summarize_local_ex recvd")
    print(f"field_arg={field_arg}") if field_arg else None
    print(f"comments={comments}")

    # Optionally, you could pass field_arg to your summarizer if needed
    # For now, we just include it in the call if supported:
    summary = local_summarizer.summarize_ex(comments, field=field_arg) if field_arg else local_summarizer.summarize(comments)

    print(f"llm response={summary}")

    return {"summary": summary}


@app.post("/summarize_local")
def summarize_local(comments: list[str]):
    return {"summary": local_summarizer.summarize(comments)}

# this isn't used, so delete it at some point
@app.post("/summarize_local_str")
def summarize_local(comments: str):
    return {"summary": local_summarizer.summarize_str(comments)}


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



    # Model context limits (tokens)
    MODEL_CONTEXT_LIMITS = {
        "gpt-3.5-turbo": 4096,
        "gpt-3.5-turbo-16k": 16384,
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-turbo": 128000,   # GPT-4 Turbo 128k
    }

    def summarize(self, comments: list[str], completion_tokens: int = 500) -> str:
        if not comments:
            return "No comments available."

        model_limit = self.MODEL_CONTEXT_LIMITS.get(self.model_name, 4096)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Helper to count tokens for a given model
        def count_tokens(text: str) -> int:
            enc = tiktoken.encoding_for_model(self.model_name)
            return len(enc.encode(text))

        # Split comments into chunks
        chunks = []
        chunk_token_counts = []
        current_chunk = []
        current_tokens = 0
        total_tokens = 0

        for comment in comments:
            comment_tokens = count_tokens(comment)
            total_tokens += comment_tokens
            
            if comment_tokens > max_tokens_per_chunk:
                comment = comment[:max_tokens_per_chunk]  # truncate large comment
                comment_tokens = max_tokens_per_chunk

            if current_tokens + comment_tokens > max_tokens_per_chunk:
                chunk_text = "\n".join(current_chunk)
                chunks.append(chunk_text)
                chunk_token_counts.append(current_tokens)
                current_chunk = [comment]
                current_tokens = comment_tokens
            else:
                current_chunk.append(comment)
                current_tokens += comment_tokens

        if current_chunk:
            chunk_text = "\n".join(current_chunk)
            chunks.append(chunk_text)
            chunk_token_counts.append(current_tokens)

        # Print token statistics
        print(f"[INFO] Total tokens across all comments: {total_tokens}")
        print(f"[INFO] Number of chunks: {len(chunks)}")
        for i, token_count in enumerate(chunk_token_counts, 1):
            print(f"[INFO] Chunk {i} tokens: {token_count}")

        # Summarize each chunk
        summaries = []
        for chunk in chunks:
            prompt = self._summarize_prompt(chunk)

            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response.choices[0].message.content)
            except openai.OpenAIError as e:
                    print("API error:", e)

        # Combine chunk summaries if multiple
        if len(summaries) > 1:
            combined_prompt = self._summarize_prompt("\n".join(summaries))
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response.choices[0].message.content
            except OpenAIError as e:
                final_summary = "[Final summary failed due to API error]"
        else:
            final_summary = summaries[0]

        return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name}) {final_summary}"




    def summarize_old(self, comments: list[str]) -> str:
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


    def summarize_ex(self, comments: List[str], field: Optional[str] = None, completion_tokens: int = 500) -> str:
        if not comments:
            return "No comments available."

        model_limit = self.MODEL_CONTEXT_LIMITS.get(self.model_name, 4096)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Count tokens for this model
        def count_tokens(text: str) -> int:
            enc = tiktoken.encoding_for_model(self.model_name)
            return len(enc.encode(text))

        # Split a single comment into token-constrained chunks
        def split_comment_into_chunks(comment: str) -> List[str]:
            enc = tiktoken.encoding_for_model(self.model_name)
            tokens = enc.encode(comment)

            chunks = []
            for i in range(0, len(tokens), max_tokens_per_chunk):
                token_slice = tokens[i:i + max_tokens_per_chunk]
                chunks.append(enc.decode(token_slice))

            return chunks

        # Build final list of text chunks (token safe)
        chunks = []
        for comment in comments:
            comment_tokens = count_tokens(comment)

            if comment_tokens > max_tokens_per_chunk:
                # split big comments instead of truncating
                parts = split_comment_into_chunks(comment)
                chunks.extend(parts)
            else:
                chunks.append(comment)

        # Token statistics
        print(f"[INFO] Number of chunks: {len(chunks)}")
        for i, chunk in enumerate(chunks, start=1):
            print(f"[INFO] Chunk {i} tokens: {count_tokens(chunk)}")

        # Prompt template (fixed original bug)
        if field:
            prompt_template = "{field}. Here's the text:\n{chunk}"
        else:
            prompt_template = "The following is the content you need to summarize:\n{chunk}"

        # Summarize each chunk
        summaries = []
        for chunk in chunks:
            prompt = prompt_template.format(field=field, chunk=chunk)

            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response.choices[0].message.content)
            except Exception as e:
                print(f"[ERROR] OpenAI API error: {e}")
                summaries.append("[Chunk summary failed]")

        # If only one chunk, return result
        if len(summaries) == 1:
            final_summary = summaries[0]
        else:
            # Combine all summaries
            joined = "\n".join(summaries)

            # Construct final synthesis prompt
            if field:
                combined_prompt = f"{field}. Here's the text:\n{joined}"
            else:
                combined_prompt = f"The following is the content you need to summarize:\n{joined}"

            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response.choices[0].message.content
            except Exception as e:
                print(f"[ERROR] OpenAI API error in final summary: {e}")
                final_summary = "[Final summary failed due to API error]"

        return f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {self.model_name})\n{final_summary}"



    #def summarize_ex(self, comments: list[str]) -> str:
    def summarize_ex_old(self, comments: List[str], field: Optional[str] = None) -> str:
        if not comments:
            return "No comments available."

        # Convert list to a string for summarization
        comments_text = "\n".join(comments)

         # Use the field as the prompt if provided
        if field:
            prompt = f"{field}. Here's the text: {comments}"
        else:
            #prompt = f"The following is the content you need to summarize:\n{comments_text}"
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


@app.post("/summarize_openai_ex")
def summarize_openai_ex(payload: SummarizeRequest):
    comments = payload.comments
    field_arg = payload.field

    print(f"/summarize_openai_ex recvd")
    print(f"field_arg={field_arg}") if field_arg else None
    print(f"comments={comments}")


    # Optionally, you could pass field_arg to your summarizer if needed
    # For now, we just include it in the call if supported:
    summary = openai_summarizer.summarize_ex(comments, field=field_arg) if field_arg else local_summarizer.summarize(comments)

    print(f"llm response={summary}")

    return {"summary": summary}

@app.post("/summarize_openai")
def summarize_openai(comments: list[str]):
    return {"summary": openai_summarizer.summarize(comments)}

'''# this isn't used, so delete it at some point
@app.post("/summarize_openai_str")
def summarize_openai_str(comments: str):
    return {"summary": openai_summarizer.summarize_str(comments)}
'''



# Create one global summarizer instance
claude_summarizer = ClaudeSummarizer(MODEL_NAME3)


@app.post("/summarize_claude_ex")
def summarize_claude_ex(payload: SummarizeRequest):
    comments = payload.comments
    field_arg = payload.field

    print(f"/summarize_claude_ex recvd")
    print(f"field_arg={field_arg}") if field_arg else None
    print(f"comments={comments}")

    # Use field_arg if provided, otherwise use standard summarize
    summary = claude_summarizer.summarize_ex(comments, field=field_arg) if field_arg else claude_summarizer.summarize(comments)

    print(f"llm response={summary}")

    return {"summary": summary}


@app.post("/summarize_claude")
def summarize_claude(comments: list[str]):
    return {"summary": claude_summarizer.summarize(comments)}