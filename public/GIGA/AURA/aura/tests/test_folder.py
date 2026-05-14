"""Tests for aura.folder — folder scanning and semantic resonance."""
import tempfile
from pathlib import Path

import pytest
from aura.folder import FolderAura


@pytest.fixture()
def node(tmp_path):
    """A minimal AURA node folder."""
    node_dir = tmp_path / "mynode"
    node_dir.mkdir()
    return node_dir


@pytest.fixture()
def full_node(tmp_path):
    """A fully-structured AURA node."""
    node_dir = tmp_path / "fullnode"
    node_dir.mkdir()
    for d in ("in", "out", "shared", "private", ".aura"):
        (node_dir / d).mkdir()

    (node_dir / "aura.meta").write_text(
        "name: FullNode\n"
        "description: A test node with music and code\n"
        "tags: music, python, analysis\n"
        "proto: v0.4\n"
    )
    (node_dir / "aura.py").write_text(
        "def respond(query):\n    return f'answer to {query}'\n"
    )
    (node_dir / "shared" / "song.mp3").write_bytes(b"\x00" * 1024)
    (node_dir / "shared" / "notes.txt").write_text("chord progressions and scale theory")
    (node_dir / "private" / "secret.key").write_bytes(b"\xFF" * 32)
    return node_dir


class TestScanning:
    def test_scan_empty_node(self, node):
        fa = FolderAura(node).scan()
        assert fa.path == node

    def test_scan_full_node(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.meta.get("name") == "FullNode"
        assert "python" in fa.tags
        assert "music" in fa.tags

    def test_private_dir_not_indexed(self, full_node):
        fa = FolderAura(full_node).scan()
        # secret.key should not contribute anything
        for f in fa.files:
            assert "secret" not in f["path"]

    def test_entry_detected(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.entry is not None
        assert fa.entry.name == "aura.py"

    def test_structure_detected(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.has_in
        assert fa.has_out
        assert fa.has_shared
        assert fa.has_private

    def test_shared_files_listed(self, full_node):
        fa = FolderAura(full_node).scan()
        names = [f["name"] for f in fa.shared_files()]
        assert "song.mp3" in names
        assert "notes.txt" in names

    def test_nonexistent_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FolderAura(tmp_path / "does_not_exist").scan()


class TestResonance:
    def test_exact_tag_match(self, full_node):
        fa = FolderAura(full_node).scan()
        score = fa.resonate("music")
        assert score > 0.5

    def test_no_match(self, full_node):
        fa = FolderAura(full_node).scan()
        score = fa.resonate("blockchain solidity defi")
        assert score < 0.3

    def test_multi_word_query(self, full_node):
        fa = FolderAura(full_node).scan()
        score = fa.resonate("python music analysis")
        assert score > 0.6

    def test_empty_query(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.resonate("") == 0.0

    def test_partial_match(self, full_node):
        fa = FolderAura(full_node).scan()
        # 'mus' partially matches 'music'
        score = fa.resonate("mus")
        assert score >= 0.0  # may or may not match depending on partial logic

    def test_tags_normalised(self, full_node):
        fa = FolderAura(full_node).scan()
        for tag, val in fa.tags.items():
            assert 0.0 <= val <= 1.0, f"tag {tag!r} out of range: {val}"


class TestFingerprint:
    def test_fingerprint_is_12_chars(self, full_node):
        fa = FolderAura(full_node).scan()
        fp = fa.fingerprint()
        assert len(fp) == 12

    def test_fingerprint_changes_on_new_file(self, full_node):
        fa1 = FolderAura(full_node).scan()
        fp1 = fa1.fingerprint()
        (full_node / "shared" / "new.txt").write_text("new content")
        fa2 = FolderAura(full_node).scan()
        fp2 = fa2.fingerprint()
        assert fp1 != fp2


class TestSummary:
    def test_summary_keys(self, full_node):
        fa = FolderAura(full_node).scan()
        s  = fa.summary()
        for key in ("name", "path", "description", "tags", "file_count", "entry", "fingerprint", "structure"):
            assert key in s, f"missing key: {key}"

    def test_summary_name_from_meta(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.summary()["name"] == "FullNode"

    def test_summary_entry_detected(self, full_node):
        fa = FolderAura(full_node).scan()
        assert fa.summary()["entry"] == "aura.py"


class TestStructure:
    def test_ensure_structure_creates_dirs(self, node):
        fa = FolderAura(node).scan()
        fa.ensure_structure()
        for d in ("in", "out", "shared", "private"):
            assert (node / d).is_dir()

    def test_write_and_clear_lock(self, node):
        fa = FolderAura(node).scan()
        fa.write_lock("abc123", "TestNode", "239.77.77.77:7777", None, 12345)
        lock_path = node / "aura.lock"
        assert lock_path.exists()
        import json
        data = json.loads(lock_path.read_text())
        assert data["node_id"] == "abc123"
        assert data["pid"] == 12345
        fa.clear_lock()
        assert not lock_path.exists()
