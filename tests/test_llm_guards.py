import pytest

from llm import (
    _DBSession,
    _format_context,
    _one_line,
    _summarize_tool_input,
    _summarize_tool_result,
    _tier2_reason,
)


class TestTier2Reason:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            ("DROP TABLE users", "DROP statement"),
            ("truncate orders", "TRUNCATE statement"),
            ("ALTER TABLE t ADD COLUMN x int", "ALTER statement"),
            ("CREATE INDEX idx ON t (a)", "CREATE statement"),
            ("GRANT ALL ON t TO bob", "GRANT statement"),
            ("REVOKE ALL ON t FROM bob", "REVOKE statement"),
            ("REINDEX TABLE t", "REINDEX statement"),
            ("COMMENT ON TABLE t IS 'x'", "COMMENT ON statement"),
        ],
    )
    def test_structural_statements_flagged(self, sql, expected):
        assert _tier2_reason(sql) == expected

    def test_multi_statement_payload_caught(self):
        assert _tier2_reason("SELECT 1; DROP TABLE users") == "DROP statement"

    def test_update_without_where(self):
        assert _tier2_reason("UPDATE t SET a = 1") == "UPDATE without WHERE"

    def test_delete_without_where(self):
        assert _tier2_reason("delete from t") == "DELETE without WHERE"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "UPDATE t SET a = 1 WHERE id = 2",
            "DELETE FROM t WHERE id = 2",
            "INSERT INTO t (a) VALUES (1)",
            "EXPLAIN SELECT 1",
            "WITH x AS (SELECT 1) SELECT * FROM x",
        ],
    )
    def test_safe_statements_pass(self, sql):
        assert _tier2_reason(sql) is None


class TestDBSessionPolicy:
    def test_check_tier2_blocks_by_default(self):
        session = _DBSession(allow_destructive=False)
        with pytest.raises(PermissionError):
            session._check_tier2("DROP TABLE users")

    def test_check_tier2_allows_when_authorized(self):
        session = _DBSession(allow_destructive=True)
        session._check_tier2("DROP TABLE users")  # must not raise

    def test_check_tier2_allows_reads(self):
        session = _DBSession(allow_destructive=False)
        session._check_tier2("SELECT 1")  # must not raise

    def test_dispatch_unknown_tool(self):
        session = _DBSession()
        result, is_error = session.dispatch("not_a_tool", {})
        assert is_error
        assert "unknown tool" in result["error"]

    def test_dispatch_tier2_blocked_returns_error_payload(self):
        # PermissionError must surface as a structured tool error, not crash,
        # and must not require a live DB connection (check happens first).
        session = _DBSession(allow_destructive=False)
        result, is_error = session.dispatch("run_query", {"sql": "TRUNCATE t"})
        assert is_error
        assert result["error"] == "PermissionError"
        assert "Tier 2" in result["message"]

    def test_explain_analyze_rejected_for_writes(self):
        session = _DBSession(allow_destructive=True)
        result, is_error = session.dispatch(
            "explain", {"sql": "DELETE FROM t WHERE id = 1", "analyze": True}
        )
        assert is_error
        assert result["error"] == "PermissionError"

    def test_close_without_connection_is_noop(self):
        _DBSession().close()  # must not raise


class TestFormatting:
    def test_one_line_collapses_whitespace(self):
        assert _one_line("a\n  b\t c") == "a b c"

    def test_one_line_truncates(self):
        s = "x" * 200
        out = _one_line(s, limit=88)
        assert len(out) == 88
        assert out.endswith("…")

    def test_format_context_empty(self):
        assert _format_context([]) == "(no context retrieved)"

    def test_format_context_blocks(self):
        blocks = [
            {"id": "users:1", "score": 0.91234, "fields": {"chunk_text": "hello"}},
            {"id": "users:2", "score": 0.5, "fields": {}},
        ]
        out = _format_context(blocks)
        assert "[users:1] (score=0.912)" in out
        assert "hello" in out
        assert "[users:2]" in out

    def test_summarize_tool_input(self):
        assert _summarize_tool_input("inspect_schema", {}) == "list tables in public"
        assert _summarize_tool_input("inspect_schema", {"table": "users"}) == "users"
        assert _summarize_tool_input("run_query", {"sql": "SELECT  1"}) == "SELECT 1"
        assert _summarize_tool_input("begin", {}) == ""

    def test_summarize_tool_result_variants(self):
        assert _summarize_tool_result({"rows": [{}], "row_count": 1}, False) == "1 row"
        assert (
            _summarize_tool_result({"rows": [], "row_count": 2, "truncated": True}, False)
            == "2 rows (truncated)"
        )
        assert _summarize_tool_result({"rowcount": 3}, False) == "3 affected"
        assert _summarize_tool_result({"tables": ["a", "b"]}, False) == "2 tables"
        assert _summarize_tool_result({"status": "committed"}, False) == "committed"
        assert (
            _summarize_tool_result({"error": "Boom", "message": "bad"}, True)
            == "Boom: bad"
        )
