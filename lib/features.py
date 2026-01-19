"""Server feature detection and configuration support.

This module provides utilities for detecting server features at runtime
and managing tests that depend on specific feature configurations.

Server Configuration Options (from ./configure):
- i64/i32: Integer size (--enable-sz=i64 or i32)
- unicode: Unicode support (--enable-unicode)
- xml: XML parsing (--enable-xml)
- waifs: Waif objects (--enable-waifs)
- waif_dict: Waif dictionary syntax (--enable-waifs=dict or --enable-def-WAIF_DICT)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class ServerFeatures:
    """Detected features of a MOO server."""

    version: str = "unknown"
    features: List[str] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)

    # Derived feature flags
    has_i64: bool = False
    has_unicode: bool = False
    has_xml: bool = False
    has_waifs: bool = False
    has_waif_dict: bool = False
    has_regexp: bool = False

    def __post_init__(self):
        """Derive feature flags from raw options."""
        # Check INT_TYPE_BITSIZE for i64
        bitsize = self.options.get('INT_TYPE_BITSIZE', 32)
        self.has_i64 = (bitsize == 64)

        # Features from server_version("features")
        self.has_unicode = 'unicode' in self.features
        self.has_xml = 'xml' in self.features
        self.has_waifs = 'waif' in self.features or 'waifs' in self.features
        self.has_regexp = 'regexp' in self.features

        # WAIF_DICT can be in options (as #-1 meaning enabled when waifs active)
        waif_dict_opt = self.options.get('WAIF_DICT')
        # #-1 means enabled, {0} or None means disabled
        self.has_waif_dict = self.has_waifs and (waif_dict_opt == '#-1' or waif_dict_opt is True)

    @property
    def config_name(self) -> str:
        """Generate a configuration name from detected features."""
        parts = []
        if self.has_i64:
            parts.append('i64')
        else:
            parts.append('i32')

        if self.has_unicode:
            parts.append('unicode')
        if self.has_xml:
            parts.append('xml')
        if self.has_waifs:
            parts.append('waifs')
            if self.has_waif_dict:
                parts.append('waif_dict')

        return '_'.join(parts) if parts else 'default'

    def supports(self, *required_features: str) -> bool:
        """Check if all required features are available."""
        feature_map = {
            'i64': self.has_i64,
            'i32': not self.has_i64,
            'unicode': self.has_unicode,
            'xml': self.has_xml,
            'waifs': self.has_waifs,
            'waif_dict': self.has_waif_dict,
            'regexp': self.has_regexp,
        }
        return all(feature_map.get(f, False) for f in required_features)


def detect_features(client) -> ServerFeatures:
    """Detect features from a connected MOO client.

    Args:
        client: A connected MooClient instance

    Returns:
        ServerFeatures with detected configuration
    """
    features = ServerFeatures()

    # Get version
    success, result = client.eval('server_version();')
    if success:
        features.version = result.strip('"')

    # Get features list
    success, result = client.eval('server_version("features");')
    if success and result.startswith('{'):
        # Parse MOO list: {"feat1", "feat2"}
        content = result[1:-1]
        for item in content.split(','):
            item = item.strip().strip('"')
            if item:
                features.features.append(item)

    # Get options dict
    success, result = client.eval('server_version("options");')
    if success and result.startswith('{'):
        features.options = _parse_options_list(result)

    # Recalculate derived flags
    features.__post_init__()

    return features


def _parse_options_list(moo_list: str) -> Dict[str, Any]:
    """Parse a MOO options list into a dictionary.

    The format is: {{"key1", value1}, {"key2", value2}, ...}
    Values can be:
    - Numbers: 64
    - Strings: "value"
    - Object refs: #-1 (true), {0} (false)
    """
    options = {}

    # Simple parser for the nested list format
    # Remove outer braces
    content = moo_list.strip()[1:-1]

    # Find each {key, value} pair
    depth = 0
    current = ""
    pairs = []

    for char in content:
        if char == '{':
            depth += 1
            if depth == 1:
                current = ""
                continue
        elif char == '}':
            depth -= 1
            if depth == 0:
                pairs.append(current.strip())
                continue
        if depth > 0:
            current += char

    # Parse each pair
    for pair in pairs:
        # Split on first comma not in quotes
        in_quotes = False
        for i, char in enumerate(pair):
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                key = pair[:i].strip().strip('"')
                value = pair[i+1:].strip()

                # Parse value
                if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                    options[key] = int(value)
                elif value.startswith('"') and value.endswith('"'):
                    options[key] = value[1:-1]
                elif value == '#-1':
                    options[key] = True
                elif value == '{0}':
                    options[key] = False
                else:
                    options[key] = value
                break

    return options


# Feature requirement constants for test marking
REQUIRES_I64 = 'i64'
REQUIRES_UNICODE = 'unicode'
REQUIRES_XML = 'xml'
REQUIRES_WAIFS = 'waifs'
REQUIRES_WAIF_DICT = 'waif_dict'
REQUIRES_REGEXP = 'regexp'
