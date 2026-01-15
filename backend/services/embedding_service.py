#!/usr/bin/env python3
"""
Embedding Service - State-of-the-art semantic embeddings for entity resolution.

Uses domain-specific transformer models for biomedical entity embeddings:
- SapBERT: Specifically designed for biomedical entity linking
- PubMedBERT: General-purpose biomedical NLP model
- BioBERT: Alternative biomedical model

These models dramatically outperform generic BERT on biomedical entity resolution.

Reference:
- SapBERT: https://arxiv.org/abs/2010.11784
- PubMedBERT: https://arxiv.org/abs/2007.15779
"""

import os
from typing import List, Optional, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
import torch
from dataclasses import dataclass

@dataclass
class EmbeddingModel:
    """Metadata for embedding models"""
    name: str
    model_id: str
    dimensions: int
    description: str
    best_for: List[str]

# Available models ranked by performance on biomedical entity linking
MODELS = {
    "sapbert": EmbeddingModel(
        name="SapBERT",
        model_id="cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
        dimensions=768,
        description="State-of-the-art for biomedical entity linking (2020)",
        best_for=["drug", "disease", "target", "company"]
    ),
    "pubmedbert": EmbeddingModel(
        name="PubMedBERT",
        model_id="microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
        dimensions=768,
        description="General-purpose biomedical NLP",
        best_for=["publication", "patent", "grant"]
    ),
    "biobert": EmbeddingModel(
        name="BioBERT",
        model_id="dmis-lab/biobert-v1.1",
        dimensions=768,
        description="Classic biomedical BERT",
        best_for=["drug", "disease"]
    )
}

class EmbeddingService:
    """
    High-performance embedding service for biomedical entities.

    Features:
    - Lazy loading (models loaded on first use)
    - GPU acceleration if available
    - Batch processing for efficiency
    - Model caching
    """

    def __init__(self, model_name: str = "sapbert", use_gpu: bool = True):
        """
        Initialize embedding service.

        Args:
            model_name: Which model to use ('sapbert', 'pubmedbert', 'biobert')
            use_gpu: Use GPU if available (dramatically faster)
        """
        if model_name not in MODELS:
            raise ValueError(f"Unknown model: {model_name}. Choose from {list(MODELS.keys())}")

        self.model_name = model_name
        self.model_info = MODELS[model_name]
        self.model: Optional[SentenceTransformer] = None
        self.device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"

        print(f"✓ Embedding service initialized: {self.model_info.name} ({self.device})")

    def load_model(self) -> None:
        """Lazy load the transformer model (happens on first encode)"""
        if self.model is not None:
            return

        print(f"Loading {self.model_info.name} model...")
        self.model = SentenceTransformer(self.model_info.model_id, device=self.device)

        if self.device == "cuda":
            print(f"✓ Model loaded on GPU: {torch.cuda.get_device_name(0)}")
        else:
            print(f"✓ Model loaded on CPU (consider GPU for 10-50x speedup)")

    def encode(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = False,
        normalize: bool = True
    ) -> np.ndarray:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of entity names/descriptions to embed
            batch_size: Process this many at once (tune for GPU memory)
            show_progress: Show progress bar
            normalize: L2 normalize embeddings (recommended for cosine similarity)

        Returns:
            Array of shape (len(texts), 768) with embeddings
        """
        self.load_model()

        # Convert to list if single string
        if isinstance(texts, str):
            texts = [texts]

        # Generate embeddings
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=normalize,
            convert_to_numpy=True
        )

        return embeddings

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        """Convenience method to encode a single text"""
        return self.encode([text], normalize=normalize)[0]

    def similarity(self, text1: str, text2: str) -> float:
        """
        Calculate cosine similarity between two texts.

        Returns:
            Similarity score from 0.0 to 1.0 (higher = more similar)
        """
        emb1, emb2 = self.encode([text1, text2], normalize=True)
        return float(np.dot(emb1, emb2))

    def find_similar(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 5
    ) -> List[Tuple[int, str, float]]:
        """
        Find most similar candidates to query.

        Args:
            query: The text to match
            candidates: List of candidate texts
            top_k: Return top K matches

        Returns:
            List of (index, candidate, similarity_score) tuples
        """
        if not candidates:
            return []

        # Encode query and all candidates
        query_emb = self.encode_single(query, normalize=True)
        candidate_embs = self.encode(candidates, normalize=True)

        # Calculate cosine similarities
        similarities = np.dot(candidate_embs, query_emb)

        # Get top K
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = [
            (int(idx), candidates[idx], float(similarities[idx]))
            for idx in top_indices
        ]

        return results

    def get_model_info(self) -> dict:
        """Get information about the current model"""
        return {
            "name": self.model_info.name,
            "model_id": self.model_info.model_id,
            "dimensions": self.model_info.dimensions,
            "description": self.model_info.description,
            "best_for": self.model_info.best_for,
            "device": self.device,
            "loaded": self.model is not None
        }

# Global singleton service
_embedding_service: Optional[EmbeddingService] = None

def get_embedding_service(model_name: str = "sapbert", use_gpu: bool = True) -> EmbeddingService:
    """
    Get the global embedding service instance (singleton pattern).

    Using singleton avoids loading models multiple times (expensive).
    """
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = EmbeddingService(model_name=model_name, use_gpu=use_gpu)

    return _embedding_service

# Example usage
if __name__ == "__main__":
    # Initialize service
    service = get_embedding_service("sapbert")

    # Example: Drug name resolution
    query = "Ibuprofen"
    candidates = [
        "Ibuprofen",
        "Ibuprophen",  # Misspelling
        "Advil",  # Brand name
        "Aspirin",  # Different drug
        "Acetaminophen"  # Different drug
    ]

    print(f"\nQuery: {query}")
    print("Candidates and similarity scores:")

    results = service.find_similar(query, candidates, top_k=5)
    for idx, candidate, score in results:
        print(f"  {candidate:20s} → {score:.4f}")

    # Expected output:
    # Ibuprofen      → 1.0000 (exact match)
    # Ibuprophen     → 0.95+  (misspelling, but semantically identical)
    # Advil          → 0.85+  (brand name, semantically related)
    # Aspirin        → 0.70+  (different drug, but same class)
    # Acetaminophen  → 0.65+  (different drug, different class)
