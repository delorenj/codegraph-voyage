# codegraph-voyage

Hybrid semantic retrieval sidecar for CodeGraph. Builds symbol-level documents from `.codegraph/codegraph.db`, generates embedding vectors, stores them in `.codegraph/codegraph-voyage.db`, and fuses lexical and vector candidates using weighted Reciprocal Rank Fusion (RRF).

## Providers

- **AutomaticAI (`automaticai`)**: Private LLM gateway at `https://api.automaticai.io/v1/embeddings`. Uses `AUTOMATICAI_API_KEY` (or 1Password `op://DeLoSecrets/NewAPI Virtual Keys/codegraph-voyage`). Defaults to `voyage-4`. Aliases: `automatic_ai`, `automatic-ai`, `aai`.
- **OpenRouter (`openrouter`)**: OpenAI-compatible embedding API at `https://openrouter.ai/api/v1/embeddings`. Requires `OPENROUTER_API_KEY`. Supports any embedding model (e.g., `voyage-4`, `voyageai/voyage-code-4`, `openai/text-embedding-3-small`).
- **Voyage AI (`voyage`)**: Official Voyage embeddings API at `https://api.voyageai.com/v1/embeddings`. Requires `VOYAGE_API_KEY`. Defaults to `voyage-code-4`.
- **Fake (`fake`)**: Offline, deterministic pseudo-random embedding generator for testing and CI.

## Configuration

Configuration is loaded from TOML files with the following precedence:
1. CLI flags (`--provider`, `--model`, `--dimensions`)
2. Project-level config: `<project_root>/.codegraph/config.toml`
3. User-level XDG config: `~/.config/codegraph-voyage/config.toml` (or `$XDG_CONFIG_HOME/codegraph-voyage/config.toml`)
4. Built-in defaults (`voyage`, `voyage-code-4`, `512`)

Example `~/.config/codegraph-voyage/config.toml`:

```toml
provider = "openrouter"
model = "voyage-4"
dimensions = 512

[openrouter]
model = "voyage-4"
dimensions = 512

[voyage]
model = "voyage-code-4"
dimensions = 512
```

## CLI Usage

```bash
# Index codebase
codegraph-voyage index [--provider fake|voyage|openrouter] [--model <model>] [--dimensions <dim>]

# Hybrid search
codegraph-voyage search "<query>" [--top-k <k>] [--json]

# Status inspection
codegraph-voyage status

# CodeGraph explore integration
codegraph-voyage explore "<query>" [--max-files <n>]
```
