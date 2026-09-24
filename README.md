# codegraph-voyage

Hybrid semantic retrieval sidecar for [CodeGraph](https://github.com/nousresearch/codegraph).

## What it does

Builds symbol-level documents from a CodeGraph index, generates embedding vectors
via the Voyage AI API (or a deterministic fake for testing), stores them in a
sidecar SQLite database, and fuses lexical + vector retrieval via **weighted
reciprocal-rank fusion (RRF)**.

## The Magic: Semantic Search that actually works

Standard lexical search (grep, BM25) fails when agents ask architectural or conceptual questions. `codegraph-voyage` fixes this by leveraging Voyage AI's state-of-the-art **`voyage-code-4`** model fused with a localized lexical scorer. 

Here is what it can do on its own codebase of 394 symbols:

**Test 1: High-Level Architecture Search**  
**Query:** `"JSON-RPC server implementation handling missing methods and errors"`  
*Notice: the query never mentions "MCP", but it asks for the underlying protocol intent.*
```text
1. [file        ] mcp_server.py                             score=0.0164    provenance=lexical+vector
   Qualified: src/codegraph_voyage/mcp_server.py
```
**Result:** It flawlessly identifies the exact file that instantiates the MCP SDK (which runs JSON-RPC over stdio) and traps execution errors.

**Test 2: Deep Algorithmic Search**  
**Query:** `"How is the final score calculated combining lexical BM25 and vector similarities?"`  
*Notice: This requires understanding mathematical and algorithmic intent.*
```text
1. [file        ] ranking.py                                score=0.0161    provenance=lexical+vector
   Qualified: src/codegraph_voyage/ranking.py

2. [function    ] rank_by_lexical_similarity                score=0.0158    provenance=lexical+vector
   Qualified: rank_by_lexical_similarity
```
**Result:** It immediately pulls up `ranking.py` and isolates the exact `rank_by_lexical_similarity` function responsible for the Reciprocal Rank Fusion math.

Agents equipped with `codegraph-voyage` aren't just searching for strings; they are querying your architecture's intent.

## Setup

```bash
# No dependencies beyond stdlib (Python 3.10+)
# Optional: set VOYAGE_API_KEY for real embedding
export VOYAGE_API_KEY="paas-...-...-..."
```

## Privacy & retention risk

Source text is transmitted to Voyage AI when the Voyage provider is selected.
The locally sanitized/redacted document content is what is sent, and Voyage
AI's data-use and retention policy applies to that transmission. Embeddings can
retain information about their inputs and should still be treated as sensitive.
The sidecar also stores the sanitized document text locally alongside each
embedding for provenance. It lives at `.codegraph/codegraph-voyage.db`; deleting
that sidecar removes these local text and embedding copies without affecting the
CodeGraph index.

## Source exclusions

Before any content is sent to the remote embedding API, the sanitizer
removes or redacts:

- **Sensitive paths**: `.env`, `credentials/`, `secrets/`, `*.pem`, `*.key`,
  `.git/`, `__pycache__/`, `node_modules/`, `.venv/`, `dist/`, `build/`, etc.
- **Sensitive line patterns**: Lines matching `password=`, `api_key=`,
  `token=`, `secret=`, etc. with apparent values are replaced with a
  `[redacted]` comment.

These checks happen **locally, before the API call**. The Voyage API never
sees the excluded content.

## Commands

| Command | Description |
|---|---|
| `codegraph-voyage index` | Build documents and store embeddings |
| `codegraph-voyage search <query>` | Hybrid semantic search |
| `codegraph-voyage status` | Show sidecar & CodeGraph status |
| `codegraph-voyage explore <query>` | Search + `codegraph explore` integration |

### `index`

Reads the CodeGraph DB at `.codegraph/codegraph.db`, builds symbol-level
documents from node metadata and source line ranges, generates embeddings
via the configured provider, and stores them in `.codegraph/codegraph-voyage.db`.

Incremental: only changed/new documents are re-embedded. Stale records are
removed.

```bash
# Index with Voyage (requires VOYAGE_API_KEY)
codegraph-voyage index

# Initialize the embedding index (alias for index)
codegraph-voyage init

# Index only functions and classes
codegraph-voyage index --kind "function,class"

# Index only files matching a pattern
codegraph-voyage index --file-filter "src/auth"
```

### `search` / `semantic_candidates`

Performs hybrid lexical + vector search on the indexed corpus. Results are
fused via weighted RRF. Exact identifier and path matches are **pinned** to
the top of results.

```bash
codegraph-voyage search "user authentication"
codegraph-voyage search "AuthService" --top-k 10 --json
```

### `explore`

Runs hybrid search, then passes the top-ranked candidate symbols to
`codegraph explore` for a full dependency-graph walk.

```bash
codegraph-voyage explore "PaymentGateway" --max-files 8
codegraph-voyage explore "UserManager" --dry-run  # preview only
```

### `status`

Shows the project root, CodeGraph DB stats, and sidecar embedding status.

```bash
codegraph-voyage status
```

## Architecture

```
tools/codegraph_voyage/
├── __init__.py       # Package metadata
├── __main__.py       # python -m entry point
├── cli.py            # CLI argument parsing and command dispatch
├── document.py       # Symbol-level document construction from CodeGraph nodes
├── providers.py      # EmbeddingProvider ABC, FakeEmbeddingProvider, VoyageEmbeddingProvider
├── ranking.py        # Weighted RRF, pinned candidates, cosine similarity
├── sidecar.py        # SQLite sidecar for embedding storage with incremental indexing
├── sanitize.py       # Path/content sanitization before remote transmission
├── explore.py        # Integration with `codegraph explore` CLI
└── tests/
    ├── __init__.py
    ├── test_all.py   # Unit test suite
    └── benchmark.py  # Retrieval quality benchmark (smoke)
```

The importable Python path is `tools.codegraph_voyage` (the underscore is
standard for multi-word CLI package names).

## Offline / fake mode

The `fake` provider produces deterministic test vectors, not semantic
embeddings. It requires explicit selection for development, testing, and CI.
There is no automatic fallback to fake embeddings.

```bash
codegraph-voyage index --provider fake
```

## OpenRouter Provider

`codegraph-voyage` supports OpenRouter's OpenAI-compatible embeddings API.
Set `OPENROUTER_API_KEY` in your environment:

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
codegraph-voyage index --provider openrouter --model "voyage-4"
```

You can choose any embedding model available on OpenRouter (e.g. `voyage-4`, `voyageai/voyage-code-4`, `openai/text-embedding-3-small`).

## Voyage AI (default)

Voyage is the built-in default provider when no configuration is present.
Set `VOYAGE_API_KEY` in your environment, for example from 1Password:

```bash
export VOYAGE_API_KEY="$(op read 'op://DeLoSecrets/Voyage AI/API Key')"
codegraph-voyage init
```

`init` and `index` fail with a nonzero exit code if credentials are missing or
embedding requests fail. Failed requests leave existing embeddings
unchanged; they never generate fake embeddings instead.

The API key is **never** accepted via CLI flags to prevent secret leakage
through process listings or shell history.

## Configuration file (TOML)

You can set your default provider, model, and dimensions in a configuration file:
- User-level XDG config: `~/.config/codegraph-voyage/config.toml` (or `$XDG_CONFIG_HOME/codegraph-voyage/config.toml`)
- Project-level config: `.codegraph/config.toml` in your repository root
- Custom config: pass `--config /path/to/config.toml` or set `CODEGRAPH_VOYAGE_CONFIG`

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

Configuration precedence (highest to lowest):
1. CLI flags (`--provider`, `--model`, `--dimensions`)
2. Project configuration (`<project>/.codegraph/config.toml`)
3. User XDG configuration (`~/.config/codegraph-voyage/config.toml`)
4. Built-in defaults (`voyage`, `voyage-code-4`, `512`)

## Benchmark

A smoke benchmark is included to verify the retrieval pipeline works:

```bash
python -m codegraph_voyage.tests.benchmark
```

This uses a tiny synthetic corpus (10 documents, 5 queries). It reports
Recall@5, MRR, and NDCG@10 separately for lexical, vector, and fused
strategies. **No quality-lift claims should be made from these results.**
The benchmark exists to verify that the pipeline produces measurable output
and that fusion can improve over the worst single strategy.

## Testing

```bash
python -m codegraph_voyage.tests.test_all
```

## Publishing

Publishing a GitHub release runs `.github/workflows/python-publish.yml` to
build and validate the wheel and source distribution, then upload both to
PyPI using trusted publishing (no API token).

Before the first release, configure a [PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/):

- PyPI project: `codegraph-voyage`
- GitHub owner: `delorenj`
- Repository: `codegraph-voyage`
- Workflow filename: `python-publish.yml`
- Environment: `pypi`

For a new PyPI project, add a pending publisher at
<https://pypi.org/manage/account/publishing/>. For an existing project, use
its Publishing settings. Set a new version in `pyproject.toml`, update
`uv.lock` with `uv lock`, commit and push, then publish a GitHub release
with a matching tag (for example, `v0.1.0`). Each PyPI version can only be
uploaded once.

## Limitations

- **Small corpus**: Real-world benefit requires hundreds of indexed symbols.
- **Lexical ranker**: Uses a simple TF-IDF-like scorer, not a full BM25
  implementation. Adequate for moderate queries but not tuned for maximum
  lexical precision.
- **Vector search**: Brute-force cosine similarity. For large corpora
  (>10K vectors), an approximate nearest-neighbor index would be needed.
- **Sidecar DB**: All embeddings are stored in a single SQLite database.
  For very large projects, consider sharding by model or module.
- **Voyage API**: Requires network access. The `input_type` parameter is
  set to `document` for indexing and `query` for search queries, as
  recommended by Voyage AI's documentation.
- **No `requests` dependency**: The Voyage provider uses `urllib.request`
  from stdlib, so no pip install is needed for the runtime.
