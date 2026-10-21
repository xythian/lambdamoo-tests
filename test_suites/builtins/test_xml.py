"""XML parsing builtins (XML-001 onward), in servers built with --enable-xml.

Both functions turn a document into nested {name, attributes, text, children}
lists.  xml_parse_tree() gathers each element's text into its text slot;
xml_parse_document() leaves the text slot empty and keeps text as string
children, in document order.
"""

import pytest

from lib.assertions import assert_moo_raises, assert_moo_success


pytestmark = pytest.mark.usefixtures("requires_xml")

SAMPLE = '<foo a=\\"1\\"><bar>11</bar>tail</foo>'


class TestParseTree:
    """xml_parse_tree()."""

    def test_xml_001_element_attributes_text(self, client):
        """XML-001: Text is gathered into the element's text slot."""
        result = assert_moo_success(client.eval(f'xml_parse_tree("{SAMPLE}")'))
        assert result == '{"foo", {{"a", "1"}}, "tail", {{"bar", {}, "11", {}}}}'

    def test_xml_002_attributes_in_order(self, client):
        """XML-002: Attributes are {name, value} pairs in document order."""
        result = assert_moo_success(client.eval('xml_parse_tree("<a b=\\"x\\" c=\\"y\\"/>")'))
        assert result == '{"a", {{"b", "x"}, {"c", "y"}}, "", {}}'

    def test_xml_003_entities_decoded(self, client):
        """XML-003: Character entities are decoded."""
        result = assert_moo_success(client.eval('xml_parse_tree("<a>&lt;&amp;&gt;</a>")'))
        assert result == '{"a", {}, "<&>", {}}'

    def test_xml_004_unprintable_bytes_escaped(self, client):
        """XML-004: Text that is not printable ASCII comes back as a MOO binary string."""
        assert assert_moo_success(client.eval('xml_parse_tree("<a>&#10;~</a>")')) == '{"a", {}, "~0a~7e", {}}'

    def test_xml_005_nested_children(self, program):
        """XML-005: Children nest to any depth."""
        doc = "<r>" + "<n>" * 20 + "x" + "</n>" * 20 + "</r>"
        result, _ = program([
            f't = xml_parse_tree("{doc}");',
            "d = 0;",
            "while (t[4])",
            "  t = t[4][1];",
            "  d = d + 1;",
            "endwhile",
            "return {d, t[3]};",
        ])
        assert assert_moo_success(result) == '{20, "x"}'


class TestParseDocument:
    """xml_parse_document()."""

    def test_xml_010_text_kept_in_order(self, client):
        """XML-010: Text stays among the children, in order, and the text slot is empty."""
        result = assert_moo_success(client.eval(f'xml_parse_document("{SAMPLE}")'))
        assert result == '{"foo", {{"a", "1"}}, "", {{"bar", {}, "", {"11"}}, "tail"}}'

    def test_xml_011_mixed_content(self, client):
        """XML-011: Text before, between and after child elements keeps its place."""
        result = assert_moo_success(client.eval('xml_parse_document("<a>x<b/>y<c>z</c></a>")'))
        assert result == '{"a", {}, "", {"x", {"b", {}, "", {}}, "y", {"c", {}, "", {"z"}}}}'


class TestErrors:
    """Malformed input."""

    @pytest.mark.parametrize("fn", ["xml_parse_tree", "xml_parse_document"])
    @pytest.mark.parametrize("doc", ["", "<a>", "<a></b>", "<a b=1/>", "text only"])
    def test_xml_020_malformed_raises_invarg(self, client, fn, doc):
        """XML-020: Malformed XML raises E_INVARG."""
        assert_moo_raises(client, f'{fn}("{doc}")', "E_INVARG")

    def test_xml_021_error_carries_message_and_offset(self, program):
        """XML-021: The error's message names the problem and its value is the byte offset."""
        result, _ = program([
            "try",
            '  xml_parse_tree("<a></b>");',
            "except e (E_INVARG)",
            "  return {e[2], e[3]};",
            "endtry",
        ])
        assert assert_moo_success(result) == '{"mismatched tag", 5}'

    def test_xml_022_argument_type(self, client):
        """XML-022: Both functions take a string."""
        assert_moo_raises(client, "xml_parse_tree(1)", "E_TYPE")
        assert_moo_raises(client, "xml_parse_document({})", "E_TYPE")
