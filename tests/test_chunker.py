import pytest

from data_spear.chunker import chunk_text, serialize_row


class TestSerializeRow:
    def test_basic(self):
        assert serialize_row({"id": 1, "name": "Ada"}) == "id: 1\nname: Ada"

    def test_skips_none_values(self):
        assert serialize_row({"id": 1, "email": None}) == "id: 1"

    def test_empty_row(self):
        assert serialize_row({}) == ""

    def test_keeps_falsy_non_none(self):
        assert serialize_row({"count": 0, "flag": False}) == "count: 0\nflag: False"


class TestChunkText:
    def test_empty_text_yields_nothing(self):
        assert list(chunk_text("", 100, 10)) == []

    def test_size_must_be_positive(self):
        with pytest.raises(ValueError):
            list(chunk_text("hello", 0, 0))

    def test_overlap_must_be_less_than_size(self):
        with pytest.raises(ValueError):
            list(chunk_text("hello", 10, 10))

    def test_short_text_single_chunk(self):
        assert list(chunk_text("hello world", 100, 10)) == ["hello world"]

    def test_chunks_respect_size(self):
        text = "word " * 200
        for chunk in chunk_text(text, 50, 10):
            assert len(chunk) <= 50

    def test_snaps_to_whitespace_at_chunk_ends(self):
        # End boundaries snap to whitespace; starts may land mid-word after the
        # overlap step (inherent to character overlap), so only ends are checked.
        text = "alpha beta gamma delta epsilon zeta eta theta iota"
        chunks = list(chunk_text(text, 20, 5))
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert f"{chunk} " in text, f"chunk ends mid-word: {chunk!r}"

    def test_full_coverage_no_text_lost(self):
        text = " ".join(f"w{i}" for i in range(100))
        chunks = list(chunk_text(text, 40, 10))
        pos = 0
        for chunk in chunks:
            assert chunk in text, "chunk is not a verbatim slice of the source"
            i = text.find(chunk, max(0, pos - 40))
            assert i != -1 and i <= pos, "gap between consecutive chunks"
            pos = max(pos, i + len(chunk))
        assert pos == len(text), "chunks do not reach the end of the text"

    def test_no_whitespace_text_still_terminates(self):
        text = "x" * 250
        chunks = list(chunk_text(text, 100, 20))
        assert chunks
        assert "".join(chunks)  # produced output, loop terminated

    def test_overlap_repeats_tail_content(self):
        text = " ".join(f"w{i}" for i in range(40))
        chunks = list(chunk_text(text, 60, 30))
        assert len(chunks) >= 2
        # with overlap, consecutive chunks share at least one word
        for a, b in zip(chunks, chunks[1:], strict=False):
            assert set(a.split()) & set(b.split())

    def test_zero_overlap(self):
        text = " ".join(f"w{i}" for i in range(40))
        chunks = list(chunk_text(text, 60, 0))
        assert len(chunks) >= 2
