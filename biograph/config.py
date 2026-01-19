"""
BioGraph MVP v8.3 - Configuration

Centralized configuration for BioGraph application.

Per Section 25F: Graph backend configuration (Postgres vs Neo4j).

Environment Variables:
- GRAPH_BACKEND: 'postgres' or 'neo4j' (default: 'postgres')
- NEO4J_URI: Neo4j connection URI (e.g., 'neo4j+s://xxx.databases.neo4j.io')
- NEO4J_USER: Neo4j username
- NEO4J_PASSWORD: Neo4j password
- DATABASE_URL: Postgres connection URL (for Neon)

Safe Mode (Default):
- GRAPH_BACKEND defaults to 'postgres'
- System runs entirely on Postgres (authoritative)
- Neo4j is opt-in performance optimization
"""

import os
from typing import Optional, Dict
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class GraphConfig:
    """
    Graph backend configuration.

    Determines whether to use Postgres-only or Postgres + Neo4j.
    """
    backend: str                           # 'postgres' or 'neo4j'
    neo4j_uri: Optional[str] = None
    neo4j_user: Optional[str] = None
    neo4j_password: Optional[str] = None

    def is_neo4j_enabled(self) -> bool:
        """Check if Neo4j is enabled and configured."""
        return (
            self.backend == 'neo4j'
            and self.neo4j_uri is not None
            and self.neo4j_user is not None
            and self.neo4j_password is not None
        )

    def get_neo4j_config(self) -> Optional[Dict[str, str]]:
        """Get Neo4j configuration dict (for ExplanationStoreFactory)."""
        if not self.is_neo4j_enabled():
            return None

        return {
            'uri': self.neo4j_uri,
            'user': self.neo4j_user,
            'password': self.neo4j_password
        }


@dataclass
class DatabaseConfig:
    """
    Database configuration for Postgres (Neon).

    Per Section 25A: Postgres is the sole source of truth.
    """
    database_url: str                      # Postgres connection URL


@dataclass
class BioGraphConfig:
    """
    BioGraph application configuration.

    Reads from environment variables with safe defaults.
    """
    database: DatabaseConfig
    graph: GraphConfig

    @classmethod
    def from_env(cls) -> 'BioGraphConfig':
        """
        Load configuration from environment variables.

        Returns:
            BioGraphConfig with database and graph settings

        Raises:
            ValueError: If required config is missing
        """
        # Database config (required)
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable is required. "
                "Example: postgresql://user:pass@host:5432/dbname"
            )

        database = DatabaseConfig(database_url=database_url)

        # Graph backend (optional, defaults to postgres)
        backend = os.getenv('GRAPH_BACKEND', 'postgres').lower()

        if backend not in ['postgres', 'neo4j']:
            logger.warning(
                f"Invalid GRAPH_BACKEND '{backend}', defaulting to 'postgres'. "
                f"Valid values: 'postgres', 'neo4j'"
            )
            backend = 'postgres'

        # Neo4j config (optional, only if backend=neo4j)
        neo4j_uri = os.getenv('NEO4J_URI')
        neo4j_user = os.getenv('NEO4J_USER')
        neo4j_password = os.getenv('NEO4J_PASSWORD')

        if backend == 'neo4j':
            if not (neo4j_uri and neo4j_user and neo4j_password):
                logger.warning(
                    "GRAPH_BACKEND=neo4j but Neo4j config incomplete. "
                    "Required: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. "
                    "Falling back to Postgres-only mode."
                )
                backend = 'postgres'
                neo4j_uri = None
                neo4j_user = None
                neo4j_password = None

        graph = GraphConfig(
            backend=backend,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password
        )

        logger.info(f"Graph backend: {backend}")
        if graph.is_neo4j_enabled():
            logger.info(f"Neo4j enabled: {neo4j_uri}")
        else:
            logger.info("Postgres-only mode (safe default)")

        return cls(database=database, graph=graph)

    def get_explanation_store_config(self) -> Dict[str, any]:
        """
        Get configuration dict for ExplanationStoreFactory.

        Returns:
            Dict with 'backend' and optional 'neo4j_config'
        """
        return {
            'backend': self.graph.backend,
            'neo4j_config': self.graph.get_neo4j_config()
        }


# Global config instance (lazy-loaded)
_config: Optional[BioGraphConfig] = None


def get_config() -> BioGraphConfig:
    """
    Get global BioGraph configuration.

    Lazy-loads from environment on first call.

    Returns:
        BioGraphConfig instance
    """
    global _config

    if _config is None:
        _config = BioGraphConfig.from_env()

    return _config


def reload_config() -> BioGraphConfig:
    """
    Reload configuration from environment.

    Useful for testing or hot-reload scenarios.

    Returns:
        New BioGraphConfig instance
    """
    global _config
    _config = BioGraphConfig.from_env()
    return _config
