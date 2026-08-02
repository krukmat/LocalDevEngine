from typing import List
from models.base import BaseModel
from models.ollama_model import OllamaModel

class ModelFactory:
    """
    Factory class to instantiate models based on configuration.
    Implements the Factory Pattern to centralize object creation.
    """

    def __init__(self, config: dict):
        self.config = config

    def create_role_model(self, role_name: str) -> BaseModel:
        """
        Creates a model instance for a given role based on configuration.
        
        Args:
            role_name: The name of the role (e.g., 'router', 'architect').

        Returns:
            A concrete implementation of BaseModel for that role.

        Raises:
            ValueError: If the role is not found in config.
        """
        role_cfg = self.config.get('roles', {}).get(role_name)
        if not role_cfg:
            raise ValueError(f"Role '{role_name}' not found in configuration.")

        model_name = role_cfg['model_name']
        capabilities = role_cfg.get('capabilities', [])
        api_url = "http://localhost:11434/api" # Default for local ollama
        timeout = self.config.get('pipeline', {}).get('request_timeout_seconds', 300.0)
        think = role_cfg.get('think')  # None = model/Ollama default; True/False forces it

        # In a real implementation, we might have different subclasses
        # for OpenAI, Anthropic, etc., based on the config.
        return OllamaModel(name=model_name, role=role_name, capabilities=capabilities, api_url=api_url,
                            timeout=timeout, think=think)

    def create_embedding_model(self) -> BaseModel:
        """Creates an embedding model using the configured settings."""
        embed_cfg = self.config.get('embeddings', {})
        if not embed_cfg:
            raise ValueError("Embedding configuration missing in config.")
            
        return OllamaModel(
            name=embed_cfg['model_name'],
            role="embedding",
            capabilities=["embedding"]
        )
