
import json
import subprocess
import os
import sys
from typing import Any
from mcp.server.mcpserver import MCPServer

# Initialize MCPServer server
mcp = MCPServer("codegraph-voyage")

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Helper to run the codegraph_voyage CLI as a subprocess."""
    cmd = ["codegraph-voyage"] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False
    )

@mcp.tool()
def search_codebase(query: str, top_k: int = 10) -> str:
    """
    Perform a hybrid semantic search to find symbols in the codebase related to the query.
    This is extremely useful to pinpoint where specific features, concepts, or terms are implemented.
    Returns a JSON string of ranked results.
    """
    try:
        # Default to voyage provider instead of fake
        result = _run_cli("search", query, "--top-k", str(top_k), "--json", "--provider", "voyage")
        if result.returncode != 0:
            return json.dumps({"error": result.stderr.strip()})
        return result.stdout.strip()
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def explore_codebase(query: str, max_files: int = 12) -> str:
    """
    Perform a semantic search to find symbols related to the query, and then walk the dependency graph 
    (using `codegraph explore`) to gather the full codebase context around those symbols.
    Use this to get 'wide-sprawl' context for complex features or dependencies.
    """
    try:
        # The explore command outputs text (not json currently) which is perfectly readable context
        result = _run_cli("explore", query, "--max-files", str(max_files), "--provider", "voyage")
        if result.returncode != 0:
            return json.dumps({"error": result.stderr.strip()})
        return result.stdout.strip()
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def index_codebase(kind: str = "function,class", file_filter: str = "") -> str:
    """
    Rebuild the codebase embedding index. 
    Call this if the codebase has changed significantly and you need fresh embeddings.
    """
    try:
        args = ["index", "--provider", "voyage"]
        if kind:
            args.extend(["--kind", kind])
        if file_filter:
            args.extend(["--file-filter", file_filter])
            
        result = _run_cli(*args)
        if result.returncode != 0:
            return json.dumps({"error": result.stderr.strip()})
        return result.stdout.strip()
    except Exception as e:
        return json.dumps({"error": str(e)})

def main():
    mcp.run()

if __name__ == "__main__":
    main()
