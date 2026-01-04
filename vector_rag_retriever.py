"""
Enhanced retrieval module with RAG optimization.
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from vector_retriever import *

@dataclass
class SearchResult:
    """A single search result from the vector store."""
    chunk_text: str
    score: float  # Lower is better for L2 distance
    chunk_index: int
    url: str
    metadata: Dict


def prepare_rag_context(
    user_id: str,
    query: str,
    docs_list,
    top_k: int = 5,
    score_threshold: float = None,
    include_sources: bool = True,
    deduplicate: bool = True
) -> Dict[str, any]:
    """
    Prepare optimized context for RAG (Retrieval-Augmented Generation).
    
    This function retrieves relevant chunks and formats them for LLM consumption,
    applying best practices like filtering, deduplication, and source attribution.
    
    Args:
        user_id: The user ID to search documents for
        query: Search query text
        top_k: Maximum number of chunks to return (default: 5)
        score_threshold: Optional similarity threshold (lower is better for L2 distance)
                        If None, automatically uses top 25% of results
        include_sources: Whether to include source metadata for citations
        deduplicate: Whether to remove similar/duplicate chunks
        
    Returns:
        Dict containing:
            - 'context': Formatted text ready for LLM prompt
            - 'chunks': List of chunk texts used
            - 'sources': List of source information (if include_sources=True)
            - 'metadata': Additional metadata about the retrieval
    """
    print(f"\n{'='*60}")
    print(f"PREPARE RAG CONTEXT - START")
    print(f"{'='*60}")
    print(f"User ID: {user_id}")
    print(f"Query: {query}")
    print(f"Top K: {top_k}")
    print(f"Score Threshold: {score_threshold}")
    print(f"Include Sources: {include_sources}")
    print(f"Deduplicate: {deduplicate}")
    
    from vector_retriever import VectorRetriever
    
    # Retrieve results
    print(f"\n[STEP 1] Initializing VectorRetriever...")
    try:
        retriever = VectorRetriever(user_id)
        print(f"✓ VectorRetriever initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize VectorRetriever: {e}")
        raise
    
    print(f"\n[STEP 2] Searching for documents (requesting {top_k * 2} results for filtering)...")
    try:
        #results = retriever.search(query, top_k=top_k * 2)
        for doc in docs_list:
            print(f"calling retriever.search_specific_document '{doc}' in docs_list")
            #def search_specific_document(self, url: str, query: str, top_k: int = 5) -> List[SearchResult]:
            results = retriever.search_specific_document(doc, query, top_k=top_k * 2)
        print(f"✓ Search completed: {len(results)} results retrieved")
    except Exception as e:
        print(f"✗ Search failed: {e}")
        raise
    
    if not results:
        print(f"\n✗ NO RESULTS FOUND")
        print(f"{'='*60}\n")
        return {
            'context': '',
            'chunks': [],
            'sources': [],
            'metadata': {'found_results': False}
        }
    
    # Apply score threshold filtering
    print(f"\n[STEP 3] Applying score threshold filtering...")
    if score_threshold is None:
        scores = [r.score for r in results]
        score_range = max(scores) - min(scores)
        score_threshold = min(scores) + (score_range * 0.25)
        print(f"  Auto-calculated threshold: {score_threshold:.4f}")
        print(f"  Score range: {min(scores):.4f} - {max(scores):.4f}")
    else:
        print(f"  Using provided threshold: {score_threshold:.4f}")
    
    filtered_results = [r for r in results if r.score <= score_threshold]
    print(f"  Results after threshold filter: {len(filtered_results)}")
    
    # If filtering removed everything, keep at least the top result
    if not filtered_results:
        print(f"  ⚠ All results filtered out, keeping top result")
        filtered_results = results[:1]
    
    # Limit to top_k after filtering
    before_limit = len(filtered_results)
    filtered_results = filtered_results[:top_k]
    if before_limit > top_k:
        print(f"  Limited to top {top_k} results (was {before_limit})")
    print(f"✓ Filtering complete: {len(filtered_results)} results")
    
    # Deduplicate similar chunks
    if deduplicate:
        print(f"\n[STEP 4] Deduplicating similar chunks...")
        before_dedup = len(filtered_results)
        try:
            filtered_results = _deduplicate_chunks(filtered_results)
            removed = before_dedup - len(filtered_results)
            if removed > 0:
                print(f"✓ Removed {removed} duplicate(s), {len(filtered_results)} unique results remain")
            else:
                print(f"✓ No duplicates found, all {len(filtered_results)} results are unique")
        except Exception as e:
            print(f"✗ Deduplication failed: {e}")
            print(f"  Continuing with {before_dedup} results without deduplication")
    else:
        print(f"\n[STEP 4] Skipping deduplication (disabled)")
    
    # Format context for LLM
    print(f"\n[STEP 5] Formatting context for LLM...")
    context_parts = []
    sources = []
    
    try:
        for i, result in enumerate(filtered_results, 1):
            chunk_text = result.chunk_text.strip()
            chunk_length = len(chunk_text)
            
            if include_sources:
                source_label = f"[Source {i}]"
                context_parts.append(f"{source_label}\n{chunk_text}")
                
                sources.append({
                    'id': i,
                    'url': result.url,
                    'title': result.metadata.get('title', 'Unknown'),
                    'chunk_index': result.chunk_index,
                    'score': result.score
                })
                print(f"  Source {i}: '{result.metadata.get('title', 'Unknown')[:50]}...' ({chunk_length} chars, score: {result.score:.4f})")
            else:
                context_parts.append(chunk_text)
                print(f"  Chunk {i}: {chunk_length} characters (score: {result.score:.4f})")
        
        context = "\n\n---\n\n".join(context_parts)
        total_context_length = len(context)
        print(f"✓ Context formatted: {len(context_parts)} chunks, {total_context_length} total characters")
    except Exception as e:
        print(f"✗ Failed to format context: {e}")
        raise
    
    result_dict = {
        'context': context,
        'chunks': [r.chunk_text for r in filtered_results],
        'sources': sources if include_sources else None,
        'metadata': {
            'found_results': True,
            'total_retrieved': len(results),
            'after_filtering': len(filtered_results),
            'score_threshold': score_threshold,
            'query': query
        }
    }
    
    print(f"\n{'='*60}")
    print(f"PREPARE RAG CONTEXT - SUCCESS")
    print(f"{'='*60}\n")
    
    return result_dict


def _deduplicate_chunks(results: List[SearchResult], similarity_threshold: float = 0.85) -> List[SearchResult]:
    """
    Remove near-duplicate chunks based on text similarity.
    
    Args:
        results: List of search results
        similarity_threshold: Jaccard similarity threshold (0-1) for considering duplicates
        
    Returns:
        Deduplicated list of results
    """
    if len(results) <= 1:
        return results
    
    unique_results = [results[0]]
    duplicates_found = []
    
    for idx, result in enumerate(results[1:], 2):
        is_duplicate = False
        
        for unique_idx, unique_result in enumerate(unique_results, 1):
            similarity = _jaccard_similarity(
                result.chunk_text.lower(),
                unique_result.chunk_text.lower()
            )
            
            if similarity >= similarity_threshold:
                is_duplicate = True
                duplicates_found.append((idx, unique_idx, similarity))
                print(f"    Chunk {idx} is {similarity:.2%} similar to chunk {unique_idx} - removing")
                break
        
        if not is_duplicate:
            unique_results.append(result)
    
    return unique_results


def _jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts."""
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    return intersection / union if union > 0 else 0.0


def create_rag_prompt(
    user_query: str,
    context: str,
    system_instructions: Optional[str] = None
) -> str:
    """
    Create a properly formatted RAG prompt for the LLM.
    
    Args:
        user_query: The user's original question
        context: Retrieved context from prepare_rag_context()
        system_instructions: Optional custom instructions for the LLM
        
    Returns:
        Formatted prompt string ready for LLM
    """
    print(f"\n[CREATE PROMPT] Formatting RAG prompt...")
    
    default_instructions = (
        "Use the following context to answer the question. "
        "If the answer is not contained in the context, say so clearly. "
        "When relevant, cite which source(s) you used by referring to [Source N]."
    )
    
    instructions = system_instructions or default_instructions
    
    if system_instructions:
        print(f"  Using custom instructions ({len(system_instructions)} chars)")
    else:
        print(f"  Using default instructions")
    
    prompt = f"""{instructions}

Context:
{context}

Question: {user_query}

Answer:"""
    
    print(f"✓ Prompt created: {len(prompt)} characters")
    
    return prompt


# Example usage function
def search_and_prepare_for_llm(
    user_id: str,
    query: str,
    docs_list,    
    top_k: int = 5,
    include_sources: bool = True
) -> Dict[str, any]:
    """
    Complete RAG pipeline: search, filter, format for LLM.
    
    Args:
        user_id: User ID
        query: Search query
        docs_list: List of documents load up in RAG 
        top_k: Max chunks to include
        include_sources: Whether to include source citations
        
    Returns:
        Dict with 'prompt' ready for LLM and 'metadata' about retrieval
    """
    print(f"\n{'#'*60}")
    print(f"# RAG PIPELINE - COMPLETE WORKFLOW")
    print(f"{'#'*60}")
    
    # Get prepared context
    try:
        rag_data = prepare_rag_context(
            user_id=user_id,
            query=query,
            docs_list=docs_list,
            top_k=top_k,
            include_sources=include_sources
        )
    except Exception as e:
        print(f"\n✗ RAG PIPELINE FAILED during context preparation: {e}")
        raise
    
    if not rag_data['metadata']['found_results']:
        print(f"\n⚠ NO CONTEXT AVAILABLE - Returning query without RAG context")
        print(f"{'#'*60}\n")
        return {
            'prompt': query,
            'has_context': False,
            'metadata': rag_data['metadata']
        }
    
    # Create full prompt
    try:
        full_prompt = create_rag_prompt(query, rag_data['context'])
    except Exception as e:
        print(f"\n✗ RAG PIPELINE FAILED during prompt creation: {e}")
        raise
    
    print(f"\n{'#'*60}")
    print(f"# RAG PIPELINE - COMPLETE SUCCESS")
    print(f"{'#'*60}\n")
    
    return {
        'prompt': full_prompt,
        'context': rag_data['context'],
        'has_context': True,
        'sources': rag_data['sources'],
        'metadata': rag_data['metadata']
    }


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python rag_retriever.py <user_id> <query>")
        print("Example: python rag_retriever.py NadeemH 'how to troubleshoot citrix'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    query = " ".join(sys.argv[2:])
    
    print(f"\n{'*'*60}")
    print(f"* RAG RETRIEVER - COMMAND LINE EXECUTION")
    print(f"{'*'*60}")
    print(f"User: {user_id}")
    print(f"Query: {query}")
    print(f"{'*'*60}")
    
    try:
        result = search_and_prepare_for_llm(user_id, query, top_k=5)
        
        if not result['has_context']:
            print("\n" + "="*60)
            print("NO RELEVANT CONTEXT FOUND")
            print("="*60)
            print("\nPrompt for LLM:")
            print(result['prompt'])
        else:
            print("\n" + "="*60)
            print("=== PROMPT FOR LLM ===")
            print("="*60)
            print(result['prompt'])
            
            print("\n" + "="*60)
            print("=== SOURCES USED ===")
            print("="*60)
            for source in result['sources']:
                print(f"\nSource {source['id']}: {source['title']}")
                print(f"  Score: {source['score']:.4f}")
                print(f"  URL: {source['url']}")
                print(f"  Chunk Index: {source['chunk_index']}")
            
            print("\n" + "="*60)
            print("=== METADATA ===")
            print("="*60)
            print(f"Query: {result['metadata']['query']}")
            print(f"Total chunks retrieved: {result['metadata']['total_retrieved']}")
            print(f"Chunks after filtering: {result['metadata']['after_filtering']}")
            print(f"Score threshold used: {result['metadata']['score_threshold']:.4f}")
        
        print("\n" + "*"*60)
        print("* EXECUTION COMPLETED SUCCESSFULLY")
        print("*"*60 + "\n")
        
    except Exception as e:
        print("\n" + "!"*60)
        print("! EXECUTION FAILED")
        print("!"*60)
        print(f"Error: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        print("!"*60 + "\n")
        sys.exit(1)