"""Credential fail-open tests against disposable CodeGraph documents and CLI entrypoints."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codegraph_voyage.cli import main


class TestRetrievalWithoutCredentials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.codegraph_bin = shutil.which("codegraph")
        (self.root / ".codegraph").mkdir()
        (self.root / "service.py").write_text("def auth_service():\n    return 'ok'\n")
        db = self.root / ".codegraph" / "codegraph.db"
        conn = sqlite3.connect(db)
        try:
            conn.execute("""CREATE TABLE nodes (
                id TEXT, kind TEXT, name TEXT, qualified_name TEXT,
                file_path TEXT, language TEXT, start_line INT, end_line INT,
                docstring TEXT, signature TEXT, visibility TEXT, return_type TEXT
            )""")
            conn.execute("""INSERT INTO nodes VALUES (
                'n1','function','auth_service','service.auth_service',
                'service.py','python',1,2,'Auth for public users',
                'def auth_service()','public',NULL
            )""")
            conn.commit()
        finally:
            conn.close()
        self.db = db

    def call(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "no-user-config"),
            "CODEGRAPH_VOYAGE_CONFIG": "",
            "VOYAGE_API_KEY": "",
            "CODEGRAPH_PROVIDER": "voyage",
        }, clear=True), mock.patch("urllib.request.urlopen", side_effect=AssertionError("unexpected HTTP")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = main([*argv, "--project", str(self.root)])
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_index_still_requires_key_and_does_not_create_sidecar(self):
        rc, _, err = self.call("index")
        self.assertEqual(rc, 2)
        self.assertIn("VOYAGE_API_KEY", err)
        self.assertFalse((self.root / ".codegraph" / "codegraph-voyage.db").exists())

    def test_search_and_semantic_candidates_without_sidecar(self):
        for command in ("search", "semantic_candidates"):
            with self.subTest(command=command):
                rc, stdout, err = self.call(command, "auth_service", "--json")
                self.assertEqual(rc, 0, err)
                hits = json.loads(stdout)
                self.assertEqual(hits[0]["name"], "auth_service")
                self.assertTrue(hits[0]["is_pinned"])
                self.assertIsNone(hits[0]["vector_score"])
                self.assertIn("lexical-only", err)
        self.assertFalse((self.root / ".codegraph" / "codegraph-voyage.db").exists())

    def test_missing_key_with_existing_sidecar_uses_current_graph_not_stored_vectors(self):
        from codegraph_voyage.providers import FakeEmbeddingProvider
        from codegraph_voyage.sidecar import SidecarDB
        sidecar = SidecarDB(self.root / ".codegraph" / "codegraph-voyage.db")
        sidecar.open()
        try:
            sidecar.store_embeddings([{
                "node_id": "stale", "content_hash": "h", "embedding": [0.1, 0.2],
                "node_kind": "function", "name": "stale", "qualified_name": "stale",
                "file_path": "old.py", "language": "python", "start_line": 1,
                "end_line": 1, "document_text": "stale",
            }], FakeEmbeddingProvider(dimensions=2))
        finally:
            sidecar.close()
        for command in ("search", "semantic_candidates"):
            with self.subTest(command=command):
                rc, stdout, err = self.call(command, "auth_service", "--json")
                self.assertEqual(rc, 0, err)
                self.assertEqual([hit["name"] for hit in json.loads(stdout)], ["auth_service"])
                self.assertIn("lexical-only", err)

    def test_generated_codegraph_native_explore(self):
        if not self.codegraph_bin:
            self.skipTest("codegraph CLI not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "service.py").write_text(
                "def auth_service():\n    return 'native graph result'\n"
            )
            env = {**os.environ, "CODEGRAPH_TELEMETRY": "0"}
            for key in ("VOYAGE_API_KEY", "CODEGRAPH_PROVIDER", "CODEGRAPH_VOYAGE_CONFIG"):
                env.pop(key, None)
            init = subprocess.run(
                ["codegraph", "init", str(root)], cwd=root, env=env,
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            cg = root / ".codegraph" / "codegraph.db"
            before = hashlib.sha256(cg.read_bytes()).hexdigest()
            for with_sidecar in (False, True):
                with self.subTest(with_sidecar=with_sidecar):
                    if with_sidecar:
                        from codegraph_voyage.providers import FakeEmbeddingProvider
                        from codegraph_voyage.sidecar import SidecarDB
                        db = SidecarDB(root / ".codegraph" / "codegraph-voyage.db")
                        db.open()
                        try:
                            db.store_embeddings([{
                                "node_id": "stale", "content_hash": "h", "embedding": [0.1, 0.2],
                                "node_kind": "function", "name": "stale", "qualified_name": "stale",
                                "file_path": "old.py", "language": "python", "start_line": 1,
                                "end_line": 1, "document_text": "stale",
                            }], FakeEmbeddingProvider(dimensions=2))
                        finally:
                            db.close()
                    out, err = io.StringIO(), io.StringIO()
                    with mock.patch.dict(os.environ, {
                        "XDG_CONFIG_HOME": str(root / "no-user-config"),
                        "CODEGRAPH_VOYAGE_CONFIG": "", "VOYAGE_API_KEY": "",
                        "CODEGRAPH_PROVIDER": "voyage", "CODEGRAPH_TELEMETRY": "0",
                    }, clear=True), mock.patch("urllib.request.urlopen", side_effect=AssertionError("unexpected HTTP")), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        rc = main(["explore", "auth_service", "--project", str(root),
                                   "--codegraph-bin", self.codegraph_bin])
                    self.assertEqual(rc, 0, err.getvalue())
                    self.assertIn("def auth_service():", out.getvalue())
                    self.assertIn("lexical-only", err.getvalue())
                    self.assertEqual(hashlib.sha256(cg.read_bytes()).hexdigest(), before)

    def test_installed_entrypoints_without_key(self):
        cli = shutil.which("codegraph-voyage", path=str(Path(sys.executable).parent))
        if not cli or not self.codegraph_bin:
            self.skipTest("installed CLI or codegraph CLI not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "service.py").write_text("def auth_service():\n    return 'installed result'\n")
            env = {**os.environ, "XDG_CONFIG_HOME": str(root / "no-user-config"),
                   "VOYAGE_API_KEY": "", "CODEGRAPH_PROVIDER": "voyage",
                   "CODEGRAPH_VOYAGE_CONFIG": "", "CODEGRAPH_TELEMETRY": "0"}
            init = subprocess.run([self.codegraph_bin, "init", str(root)], cwd=root,
                                  env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(init.returncode, 0, init.stderr)
            for with_sidecar in (False, True):
                with self.subTest(with_sidecar=with_sidecar):
                    if with_sidecar:
                        from codegraph_voyage.sidecar import SidecarDB
                        sidecar = SidecarDB(root / ".codegraph" / "codegraph-voyage.db")
                        sidecar.open()
                        sidecar.close()
                    for command in ("search", "semantic_candidates", "explore"):
                        args = [cli, command, "auth_service", "--project", str(root)]
                        if command == "explore":
                            args.extend(["--codegraph-bin", self.codegraph_bin])
                        else:
                            args.append("--json")
                        result = subprocess.run(args, cwd=root, env=env, text=True,
                                                capture_output=True, timeout=60)
                        self.assertEqual(result.returncode, 0, (command, result.stderr))
                        self.assertIn("lexical-only", result.stderr)
                        if command == "explore":
                            self.assertIn("def auth_service():", result.stdout)
                        else:
                            hits = json.loads(result.stdout)
                            self.assertEqual(hits[0]["name"], "auth_service")
                            self.assertTrue(hits[0]["is_pinned"])


if __name__ == "__main__":
    unittest.main()
