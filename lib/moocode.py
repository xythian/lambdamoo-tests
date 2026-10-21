"""Helpers for building MOO code from Python."""


def moo_string(text: str) -> str:
    """Quote text as a MOO string literal."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def moo_list(lines) -> str:
    """Quote a sequence of strings as a MOO list of string literals."""
    return "{" + ", ".join(moo_string(line) for line in lines) + "}"


def define_verb(client, obj, name, lines, perms="rxd", args=("this", "none", "this"), owner="player"):
    """Add a verb to obj and program it, failing if it does not compile.

    Args:
        client: Connected MooClient whose player has the permissions needed.
        obj: Object reference as MOO source, e.g. "#5".
        name: Verb name string (may hold several names).
        lines: Verb source lines.
        perms: Verb permission flags.
        args: The verb's dobj, prep and iobj argument specifiers.
        owner: MOO expression for the verb's owner.
    """
    spec = ", ".join(moo_string(a) for a in args)
    success, result = client.eval(f'add_verb({obj}, {{{owner}, "{perms}", {moo_string(name)}}}, {{{spec}}})')
    assert success, f"add_verb {obj}:{name} failed: {result}"
    first = name.split()[0].replace("*", "")
    success, result = client.eval(f"set_verb_code({obj}, {moo_string(first)}, {moo_list(lines)})")
    assert success and result == "{}", f"{obj}:{name} did not compile: {result}"
