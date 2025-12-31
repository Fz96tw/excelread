"""
Embedding strategies for vector generation.
Configure via environment variable: EMBEDDER_TYPE=sentence_transformer|openai
"""
import os
import numpy as np
from abc import ABC, abstractmethod
from typing import List


class EmbedderInterface(ABC):
    """Abstract base class for embedding strategies."""
    
    @abstractmethod
    def encode(self, texts: List[str]) -> np.ndarray:
        """
        Encode a list of texts into embeddings.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            numpy array of shape (len(texts), embedding_dim)
        """
        pass
    
    @abstractmethod
    def get_dimension(self) -> int:
        """Return the embedding dimension."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Return the embedder name/identifier."""
        pass


class SentenceTransformerEmbedder(EmbedderInterface):
    """Embedding using SentenceTransformers (local, free)."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        
    def encode(self, texts: List[str]) -> np.ndarray:
        return self.model.encode(texts)
    
    def get_dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
    
    def get_name(self) -> str:
        return f"sentence_transformer:{self.model_name}"


class OpenAIEmbedder(EmbedderInterface):
    """Embedding using OpenAI API (requires API key, costs money)."""
    
    def __init__(self, model: str = "text-embedding-3-small"):
        import openai
        self.model = model
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Dimension depends on model
        self.dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        
    def encode(self, texts: List[str]) -> np.ndarray:
        """
        Encode texts using OpenAI API.
        Note: OpenAI has rate limits and costs money.
        """
        # OpenAI can handle batches, but has limits
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        
        embeddings = [item.embedding for item in response.data]
        return np.array(embeddings)
    
    def get_dimension(self) -> int:
        return self.dimensions.get(self.model, 1536)
    
    def get_name(self) -> str:
        return f"openai:{self.model}"


class CohereEmbedder(EmbedderInterface):
    """Embedding using Cohere API (requires API key, costs money)."""
    
    def __init__(self, model: str = "embed-english-v3.0"):
        import cohere
        self.model = model
        self.client = cohere.Client(api_key=os.getenv("COHERE_API_KEY"))
        
    def encode(self, texts: List[str]) -> np.ndarray:
        response = self.client.embed(
            texts=texts,
            model=self.model,
            input_type="search_document"  # For indexing documents
        )
        return np.array(response.embeddings)
    
    def get_dimension(self) -> int:
        # embed-english-v3.0 is 1024 dims
        return 1024
    
    def get_name(self) -> str:
        return f"cohere:{self.model}"


def get_embedder() -> EmbedderInterface:
    """
    Factory function to get the configured embedder.
    
    Environment variables:
        EMBEDDER_TYPE: sentence_transformer|openai|cohere (default: sentence_transformer)
        EMBEDDER_MODEL: Specific model name (optional)
    
    Returns:
        Configured embedder instance
    """
    embedder_type = os.getenv("EMBEDDER_TYPE", "sentence_transformer").lower()
    model_name = os.getenv("EMBEDDER_MODEL")
    
    if embedder_type == "sentence_transformer":
        model = model_name or "all-MiniLM-L6-v2"
        return SentenceTransformerEmbedder(model)
    
    elif embedder_type == "openai":
        model = model_name or "text-embedding-3-small"
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY environment variable required for OpenAI embeddings")
        return OpenAIEmbedder(model)
    
    elif embedder_type == "cohere":
        model = model_name or "embed-english-v3.0"
        if not os.getenv("COHERE_API_KEY"):
            raise ValueError("COHERE_API_KEY environment variable required for Cohere embeddings")
        return CohereEmbedder(model)
    
    else:
        raise ValueError(f"Unknown embedder type: {embedder_type}")