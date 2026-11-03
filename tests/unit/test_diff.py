"""
tests/unit/test_diff.py
------------------------
Unit tests for config_officer.compliance.diff.

Run:
    pytest tests/unit/test_diff.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_officer.compliance.diff import (
    Compare,
    Config,
    _load,
    _matches,
    _valid_line,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TEMPLATE_LINES = [
    "interface GigabitEthernet0/{{ port }}",
    " description {{ any_desc }}",
    " ip address {{ ip }} {{ mask }}",
    "ntp server {{ ntp_ip }}",
    "hostname {{ name }}",
]

MATCHING_CONFIG_LINES = [
    "interface GigabitEthernet0/1",
    " description uplink-to-core",
    " ip address 10.0.0.1 255.255.255.0",
    "ntp server 192.168.1.1",
    "hostname router-A",
]

IGNORE_PATTERNS = ["ntp server", "hostname"]


# ---------------------------------------------------------------------------
# TestLoad
# ---------------------------------------------------------------------------


class TestLoad:
    def test_accepts_list(self):
        lines = ["aaa", "bbb"]
        assert _load(lines) is lines

    def test_accepts_file_path(self, tmp_path: Path):
        f = tmp_path / "cfg.txt"
        f.write_text("line1\nline2\n", encoding="utf-8")
        result = _load(str(f))
        assert result == ["line1", "line2"]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="cisco_diff"):
            _load("/nonexistent/path/cfg.txt")


# ---------------------------------------------------------------------------
# TestValid
# ---------------------------------------------------------------------------


class TestValid:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("interface Gi0/0", True),
            (" ip address 1.2.3.4 255.255.255.0", True),
            ("!", False),  # IOS comment marker
            ("", False),  # empty line
            ("   ", False),  # whitespace-only line
            ("^C", False),  # end-of-block marker
            ("^", False),  # abbreviated end-of-block marker
        ],
    )
    def test_valid(self, line: str, expected: bool):
        assert _valid_line(line) is expected


# ---------------------------------------------------------------------------
# TestMatches
# ---------------------------------------------------------------------------


class TestMatches:
    def test_exact_match(self):
        assert _matches("hostname router", "hostname router")

    def test_exact_no_match(self):
        assert not _matches("hostname router", "hostname switch")

    def test_single_placeholder(self):
        assert _matches("hostname {{ name }}", "hostname core-sw-01")

    def test_placeholder_requires_nonempty(self):
        # The regex uses (.+) so the placeholder cannot match an empty string
        assert not _matches("hostname {{ name }}", "hostname ")

    def test_multiple_placeholders(self):
        assert _matches(
            "ip address {{ ip }} {{ mask }}",
            "ip address 192.168.1.1 255.255.255.0",
        )

    def test_placeholder_does_not_match_across_lines(self):
        # fullmatch is used, so newlines cannot be hidden inside a placeholder
        assert not _matches("ntp {{ x }}", "ntp \nsomething")

    def test_no_placeholder_strict_equality(self):
        assert not _matches(
            "ip route 0.0.0.0 0.0.0.0 10.0.0.1",
            "ip route 0.0.0.0 0.0.0.0 10.0.0.2",
        )


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------


class TestConfig:
    def test_filters_comments_and_empty(self):
        lines = [
            "! this is a comment",
            "",
            "hostname router",
            "!",
        ]
        cfg = Config(lines)
        included = cfg.included()
        assert len(included) == 1
        assert included[0] == ["hostname router"]

    def test_groups_parent_and_children(self):
        lines = [
            "interface Gi0/0",
            " description WAN",
            " ip address 1.2.3.4 255.255.255.0",
            "hostname router",
        ]
        cfg = Config(lines)
        groups = cfg.included()
        # Two groups: the interface block and the hostname line
        assert len(groups) == 2
        iface = next(g for g in groups if g[0].startswith("interface"))
        assert " description WAN" in iface
        assert " ip address 1.2.3.4 255.255.255.0" in iface

    def test_single_line_parent_only(self):
        lines = ["hostname router"]
        cfg = Config(lines)
        assert cfg.included() == [["hostname router"]]

    def test_strips_trailing_whitespace(self):
        lines = ["hostname router   "]
        cfg = Config(lines)
        assert cfg.included() == [["hostname router"]]

    def test_groups_are_sorted(self):
        lines = ["ntp server 1.1.1.1", "aaa new-model", "hostname router"]
        cfg = Config(lines)
        parents = [g[0] for g in cfg.included()]
        assert parents == sorted(parents)


# ---------------------------------------------------------------------------
# TestConfigIgnore
# ---------------------------------------------------------------------------


class TestConfigIgnore:
    def test_ignore_parent_removes_whole_block(self):
        lines = [
            "ntp server 1.1.1.1",
            "interface Gi0/0",
            " description WAN",
        ]
        cfg = Config(lines, ignore_lines=["ntp server"])
        parents = [g[0] for g in cfg.included()]
        assert "ntp server 1.1.1.1" not in parents
        assert any("interface" in p for p in parents)

    def test_ignore_child_keeps_parent(self):
        lines = [
            "interface Gi0/0",
            " description SECRET",
            " ip address 1.2.3.4 255.0.0.0",
        ]
        cfg = Config(lines, ignore_lines=["description"])
        groups = cfg.included()
        iface = groups[0]
        assert " description SECRET" not in iface
        assert " ip address 1.2.3.4 255.0.0.0" in iface

    def test_ignored_returns_dropped_lines(self):
        lines = ["ntp server 1.1.1.1", "hostname router"]
        cfg = Config(lines, ignore_lines=["ntp server"])
        ignored = cfg.ignored()
        assert any("ntp server" in g[0] for g in ignored)

    def test_ignore_accepts_file(self, tmp_path: Path):
        ignore_file = tmp_path / "ignore.txt"
        ignore_file.write_text("ntp server\n", encoding="utf-8")
        lines = ["ntp server 1.1.1.1", "hostname router"]
        cfg = Config(lines, ignore_lines=str(ignore_file))
        parents = [g[0] for g in cfg.included()]
        assert "ntp server 1.1.1.1" not in parents


# ---------------------------------------------------------------------------
# TestCompare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_no_diff_when_identical(self):
        lines = ["hostname router", "ntp server 1.1.1.1"]
        diff = Compare(lines, lines)
        assert diff.missing() == []
        assert diff.additional() == []

    def test_detects_missing_parent(self):
        template = ["hostname router", "ntp server 1.1.1.1"]
        config = ["hostname router"]
        diff = Compare(template, config)
        missing = diff.missing()
        assert any("ntp server" in g[0] for g in missing)

    def test_detects_additional_parent(self):
        template = ["hostname router"]
        config = ["hostname router", "ntp server 1.1.1.1"]
        diff = Compare(template, config)
        additional = diff.additional()
        assert any("ntp server" in g[0] for g in additional)

    def test_detects_missing_child(self):
        template = [
            "interface Gi0/0",
            " description WAN",
            " ip address 1.2.3.4 255.255.255.0",
        ]
        config = [
            "interface Gi0/0",
            " ip address 1.2.3.4 255.255.255.0",
        ]
        diff = Compare(template, config)
        missing = diff.missing()
        assert any(g[0] == "interface Gi0/0" and " description WAN" in g for g in missing)

    def test_detects_additional_child(self):
        template = ["interface Gi0/0", " ip address 1.2.3.4 255.255.255.0"]
        config = [
            "interface Gi0/0",
            " ip address 1.2.3.4 255.255.255.0",
            " shutdown",
        ]
        diff = Compare(template, config)
        additional = diff.additional()
        assert any(" shutdown" in g for g in additional)

    def test_wildcard_matches_parent(self):
        template = [
            "interface GigabitEthernet0/{{ port }}",
            " description {{ desc }}",
        ]
        config = [
            "interface GigabitEthernet0/1",
            " description uplink",
        ]
        diff = Compare(template, config)
        assert diff.missing() == []
        assert diff.additional() == []

    def test_wildcard_missing_child(self):
        template = [
            "interface GigabitEthernet0/{{ port }}",
            " description {{ desc }}",
            " ip address {{ ip }} {{ mask }}",
        ]
        config = [
            "interface GigabitEthernet0/1",
            " description uplink",
            # ip address intentionally absent
        ]
        diff = Compare(template, config)
        missing = diff.missing()
        assert any("interface" in g[0] and any("ip address" in c for c in g[1:]) for g in missing)

    def test_ignore_lines_excluded_from_diff(self):
        template = TEMPLATE_LINES
        config = MATCHING_CONFIG_LINES
        # Without ignoring - everything should match
        diff_full = Compare(template, config)
        assert diff_full.missing() == []

        # With ntp/hostname ignored - ignored lines must not appear in missing
        diff_ign = Compare(template, config, ignore_lines=IGNORE_PATTERNS)
        for group in diff_ign.missing():
            assert not any("ntp" in line.lower() for line in group)
            assert not any("hostname" in line.lower() for line in group)

    def test_accepts_config_objects(self):
        tmpl_obj = Config(TEMPLATE_LINES)
        cfg_obj = Config(MATCHING_CONFIG_LINES)
        diff = Compare(tmpl_obj, cfg_obj)
        assert diff.missing() == []

    def test_empty_template(self):
        diff = Compare([], ["hostname router"])
        assert diff.missing() == []
        assert len(diff.additional()) == 1

    def test_empty_config(self):
        diff = Compare(["hostname router"], [])
        assert len(diff.missing()) == 1
        assert diff.additional() == []

    def test_pprint_missing(self):
        template = ["hostname router", "ntp server 1.1.1.1"]
        config = ["hostname router"]
        diff = Compare(template, config)
        out = diff.pprint_missing()
        assert "ntp server" in out

    def test_pprint_additional(self):
        template = ["hostname router"]
        config = ["hostname router", "ntp server 1.1.1.1"]
        diff = Compare(template, config)
        out = diff.pprint_additional()
        assert "ntp server" in out


# ---------------------------------------------------------------------------
# TestCompareDelta
# ---------------------------------------------------------------------------


class TestCompareDelta:
    def test_delta_header(self):
        diff = Compare(["hostname router"], ["hostname router"])
        out = diff.delta()
        assert out.startswith("--- template\n+++ config")

    def test_delta_missing_prefixed_minus(self):
        diff = Compare(["hostname router", "ntp server 1.1.1.1"], ["hostname router"])
        out = diff.delta()
        assert "-" in out
        assert "ntp server" in out

    def test_delta_additional_prefixed_plus(self):
        diff = Compare(["hostname router"], ["hostname router", "ntp server 1.1.1.1"])
        out = diff.delta()
        assert "+" in out
        assert "ntp server" in out

    def test_delta_no_diff_empty_sections(self):
        lines = ["hostname router"]
        diff = Compare(lines, lines)
        out = diff.delta()
        # No numbered entries should appear when there is no diff
        assert "-   1:" not in out
        assert "+   1:" not in out
