import anthropic
from typing import List, Optional
import os

# Add this near the top with other MODEL_NAME declarations
MODEL_NAME3 = "claude-sonnet-4-20250514"  # or use claude-sonnet-4-5-20250929, claude-opus-4-20250514

# Load the Claude API key from environment
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")

# Initialize Claude client
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


class ClaudeSummarizer:
    # Model context limits (tokens)
    MODEL_CONTEXT_LIMITS = {
        "claude-sonnet-4-20250514": 200000,
        "claude-sonnet-4-5-20250929": 200000,
        "claude-opus-4-20250514": 200000,
        "claude-3-5-sonnet-20241022": 200000,
        "claude-3-opus-20240229": 200000,
        "claude-3-sonnet-20240229": 200000,
        "claude-3-haiku-20240307": 200000,
    }

    def __init__(self, model_name=MODEL_NAME3):
        self.model_name = model_name
        print(f"[INFO] Using Claude model: {self.model_name}")

    def _summarize_prompt(self, comments: str) -> str:
        return (
            f"The following is the content you need to summarize:\n{comments}"
        )

    def summarize_str(self, comments: str) -> str:
        if not comments:
            return "No comments available."

        prompt = self._summarize_prompt(comments)
        
        try:
            response = claude_client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text
            return f"({self.model_name}) {summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        except Exception as e:
            print(f"[ERROR] Claude API error: {e}")
            return f"[Summary failed: {str(e)}]"

    def _count_tokens_approximate(self, text: str) -> int:
        """Approximate token count for Claude (roughly 1 token ≈ 3.5 characters)"""
        return len(text) // 3

    def summarize(self, comments: list[str], completion_tokens: int = 1024) -> str:
        if not comments:
            return "No comments available."

        model_limit = self.MODEL_CONTEXT_LIMITS.get(self.model_name, 200000)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Helper to count tokens
        def count_tokens(text: str) -> int:
            return self._count_tokens_approximate(text)

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
                comment = comment[:max_tokens_per_chunk * 3]  # truncate large comment
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
                response = claude_client.messages.create(
                    model=self.model_name,
                    max_tokens=completion_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response.content[0].text)
            except Exception as e:
                print(f"[ERROR] Claude API error: {e}")
                summaries.append("[Chunk summary failed]")

        # Combine chunk summaries if multiple
        if len(summaries) > 1:
            combined_prompt = self._summarize_prompt("\n".join(summaries))
            try:
                response = claude_client.messages.create(
                    model=self.model_name,
                    max_tokens=completion_tokens,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response.content[0].text
            except Exception as e:
                print(f"[ERROR] Claude API error in final summary: {e}")
                final_summary = "[Final summary failed due to API error]"
        else:
            final_summary = summaries[0]

        return f"({self.model_name}) {final_summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def summarize_ex(self, comments: List[str], field: Optional[str] = None, completion_tokens: int = 1024) -> str:
        if not comments:
            return "No comments available."

        model_limit = self.MODEL_CONTEXT_LIMITS.get(self.model_name, 200000)
        max_tokens_per_chunk = model_limit - completion_tokens

        # Helper to count tokens
        def count_tokens(text: str) -> int:
            return self._count_tokens_approximate(text)

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
                comment = comment[:max_tokens_per_chunk * 3]  # truncate large comment
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
                response = claude_client.messages.create(
                    model=self.model_name,
                    max_tokens=completion_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                summaries.append(response.content[0].text)
            except Exception as e:
                print(f"[ERROR] Claude API error: {e}")
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
                response = claude_client.messages.create(
                    model=self.model_name,
                    max_tokens=completion_tokens,
                    messages=[{"role": "user", "content": combined_prompt}],
                )
                final_summary = response.content[0].text
            except Exception as e:
                print(f"[ERROR] Claude API error in final summary: {e}")
                final_summary = "[Final summary failed due to API error]"
        else:
            final_summary = summaries[0]

        return f"({self.model_name}) {final_summary} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
