# RFC 001: MOO Source Module Format

**Status:** Draft
**Author:** LambdaMOO Test Suite Contributors
**Created:** 2026-01-20

## Abstract

This RFC defines a human-readable source format for MOO objects that can represent anything from a single object to an entire database. The format is designed to be git-friendly, tool-friendly, and loadable into a MOO server.

## 1. Introduction & Motivation

### Problem Statement

MOO databases are stored in a binary format that is:
- Difficult to read and edit by humans
- Poorly suited for version control (large diffs, merge conflicts)
- Hard to share and distribute as reusable components
- Not amenable to standard text-based tooling (grep, diff, editors)

### Goals

1. **Human Readable**: The format should be easy to read and write by hand
2. **Git Friendly**: Changes should produce meaningful, reviewable diffs
3. **Tool Friendly**: Standard text tools should work well with the format
4. **Loadable**: The format should be convertible to/from MOO database format
5. **Modular**: Support both complete databases and reusable object modules
6. **Faithful**: Round-trip conversion should preserve all information

### Prior Art

This format builds on existing MOO code representation patterns and extends them to cover full object definitions including properties, flags, and relationships.

## 2. Format Overview

### Design Principles

- **Custom MOO-like syntax**: The format uses a syntax that feels natural to MOO programmers, not generic formats like TOML or JSON
- **Block structure**: Objects, verbs, and other constructs use explicit `end` markers for clarity
- **Single-file and multi-file**: Both representations are supported with canonical conversion between them
- **Two modes**: Supports standalone databases (full fidelity) and importable modules (portable)

### File Extension

Source files use the `.moo` extension.

## 3. Object Declaration Syntax

Objects are declared with a block structure:

```
object <id>
  name <string>
  owner <ref>
  parent <ref>
  location <ref>
  flags <flag-list>

  <properties>

  <verbs>
endobject
```

### Object Identifiers

In database mode, objects use their numeric IDs:
```
object #0
  ...
endobject
```

In module mode, objects use symbolic names:
```
object @generic_thing
  ...
endobject
```

### Object Flags

Object flags are specified as a space-separated list:

```
flags player wizard programmer
```

Available flags:
- `player` - Object represents a player
- `programmer` - Object has programmer privileges
- `wizard` - Object has wizard privileges
- `read` - Object is readable
- `write` - Object is writable
- `fertile` - Object can be a parent (allows children)

## 4. Property Syntax

Properties appear at the start of an object, before any verbs. There are several forms:

### Defined Property with Value

```
property <name> [<flags>] = <value>
```

Examples:
```
property description = "A nondescript object."
property aliases = {"thing", "object"}
property weight readable writable = 10
```

### Inherited Property Override

When a property is inherited from a parent but this object provides its own value:

```
property <name> inherited = <value>
```

Or to inherit without overriding:
```
property <name> inherited
```

### Clear Property

A property defined on this object with no initial value:

```
property <name> clear
```

### Property Flags

Available property flags:
- `readable` / `r` - Property can be read by others
- `writable` / `w` - Property can be written by others
- `chown` / `c` - Property ownership can be changed

### Property Values

Values use MOO literal syntax:
- Strings: `"hello world"`
- Integers: `42`, `-17`
- Floats: `3.14159`
- Object references: `#123`, `$root`, `@local_obj`
- Lists: `{1, 2, 3}`, `{"a", "b"}`, `{}`
- Maps: `["key" -> value, "key2" -> value2]`
- Errors: `E_PERM`, `E_PROPNF`, etc.

## 5. Verb Syntax

Verbs come in two forms: methods (called programmatically) and commands (invoked by player input).

### Method Syntax

```
method <name> [<flags>]
  <code>
endmethod
```

Multi-word verb names (aliases):
```
method "look_self examine_self"
  <code>
endmethod
```

### Command Syntax

```
command "<pattern>" <dobj-spec> <prep> <iobj-spec> [<flags>]
  <code>
endcommand
```

Examples:
```
command "look l" any at any
  <code>
endcommand

command "put drop" this inside any
  <code>
endcommand

command "take get" this from this
  <code>
endcommand
```

Object specifiers: `this`, `any`, `none`

Prepositions: `none`, `any`, `with`, `at`, `to`, `in`, `inside`, `into`, `on`, `onto`, `from`, `over`, `through`, `under`, `behind`, `beside`, `for`, `about`, `is`, `as`, `off`

### Verb Flags

Inline flags for verbs:

```
method foo readable executable
  <code>
endmethod

method bar owner #2 perms "rxd"
  <code>
endmethod

command "wizard_cmd" none none none wizardly
  <code>
endcommand
```

Available flags:
- `readable` / `r` - Verb code can be read
- `writable` / `w` - Verb code can be modified
- `executable` / `x` - Verb can be called
- `debug` / `d` - Verb runs in debug mode
- `wizardly` - Verb has wizard-only execution
- `owner <ref>` - Specify verb owner
- `perms "<rwxd>"` - Specify permission string directly

## 6. Reference Syntax

### Object Number References

Direct numeric references:
```
#0      // Object #0 (typically $root)
#123    // Object #123
#-1     // $nothing
#-2     // $ambiguous_match
#-3     // $failed_match
```

### Built-in Symbolic Constants

```
$nothing          // #-1
$ambiguous_match  // #-2
$failed_match     // #-3
```

### External Symbolic References

References to well-known objects in the target environment:
```
$root             // The root object
$player           // Generic player
$room             // Generic room
$thing            // Generic thing
```

### Module-Qualified References

References to objects from other modules:
```
core::generic_thing
mylib::utilities
```

### Local References

References within the current module:
```
@parent           // Parent in inheritance sense
@this             // Self-reference (rarely needed)
@my_local_object  // Reference to locally-defined object
```

## 6a. Internal References

Objects defined within the same module can reference each other using local names.

### Named Object Definitions

```
object @my_thing
  name "My Thing"
  parent $thing
endobject

object @other_thing
  name "Other Thing"
  parent @my_thing    // reference to previously defined object
endobject
```

### Forward References for Cycles

When objects need to reference each other (but not in parent chains), use forward declarations:

```
forward @thing_a
forward @thing_b

object @thing_a
  name "Thing A"
  parent $thing
  property partner = @thing_b   // OK: forward declared
endobject

object @thing_b
  name "Thing B"
  parent $thing
  property partner = @thing_a   // OK: already defined
endobject
```

### Resolution Order

1. Forward declarations create placeholder references
2. Objects are defined in order; references are resolved as encountered
3. At module end, all forward references must be resolved
4. Circular property references are valid; circular parent references are not

### Errors

```
// ERROR: Undefined reference
object @foo
  property bar = @undefined_thing   // Error: @undefined_thing not declared
endobject

// ERROR: Circular parent chain
object @a
  parent @b
endobject
object @b
  parent @a    // Error: circular parent reference
endobject
```

## 7. Multi-Object Organization

### Hierarchy Mode

Objects can be nested to show parent-child relationships:

```
object @root_thing
  name "Root"

  object @child_one
    name "Child One"
    // parent is implicitly @root_thing
  endobject

  object @child_two
    name "Child Two"
    // parent is implicitly @root_thing
  endobject
endobject
```

### Flat Mode

All objects at the same level with explicit parent references:

```
object @root_thing
  name "Root"
endobject

object @child_one
  name "Child One"
  parent @root_thing
endobject

object @child_two
  name "Child Two"
  parent @root_thing
endobject
```

### Equivalence

Both modes represent the same structure. Tooling can convert between them:
- `moo-flatten`: Convert hierarchy mode to flat mode
- `moo-nest`: Convert flat mode to hierarchy mode (best-effort)

## 8. Module vs Database Mode

### Module Mode

Modules are portable, importable units:

```
module mymodule
  version "1.0.0"
  requires core >= 1.0
  requires utils
  exports @public_thing, @utility_object

object @public_thing
  name "Public Thing"
  parent $thing

  property helper = @internal_thing

  method do_something
    return @internal_thing:helper_method();
  endmethod
endobject

object @internal_thing
  name "Internal Helper"
  parent $thing

  method helper_method
    return "helped";
  endmethod
endobject

endmodule
```

Module header fields:
- `version` - Semantic version of this module
- `requires` - Dependencies on other modules (with optional version constraints)
- `exports` - Objects/symbols visible to importers

### Database Mode

Full-fidelity representation of a complete database:

```
database
  version 1
  max_object 47
  recycled {12, 23, 31}

object #0
  name "Root Class"
  owner #2
  parent $nothing
  flags fertile

  property name = ""
  property owner = #-1
  property location = #-1
  property contents = {}
endobject

object #1
  name "System Object"
  owner #2
  parent #0

  method do_login_command owner #2 perms "rxd"
    // login handling
  endmethod
endobject

object #2
  name "Wizard"
  owner #2
  parent #0
  location #3
  flags player wizard programmer
endobject

// ... all objects ...

enddatabase
```

Database header fields:
- `version` - Format version number
- `max_object` - Highest object number allocated
- `recycled` - List of recycled (deleted) object numbers

## 9. File Organization (Multi-File)

For larger modules or databases, content can be split across files:

```
mymodule/
  module.moo          # module header, imports, exports
  objects/
    generic_thing.moo
    player.moo
    room.moo
  verbs/              # optional: large verbs can be split out
    player/
      look_self.moo
```

### module.moo

```
module mymodule
  version "1.0.0"
  requires core >= 1.0
  exports @generic_thing, @player, @room

  include "objects/generic_thing.moo"
  include "objects/player.moo"
  include "objects/room.moo"
endmodule
```

### objects/generic_thing.moo

```
object @generic_thing
  name "Generic Thing"
  parent $thing

  property description = "A generic thing."

  include "../verbs/generic_thing/look_self.moo"
endobject
```

### verbs/generic_thing/look_self.moo

```
method look_self readable
  player:tell(this.description);
endmethod
```

## 10. Include/Import Directives

### Include

Inline file inclusion (text substitution):

```
include "path/to/file.moo"
```

Includes are processed relative to the including file's directory.

### Import

External module references:

```
import core                           // import all exports from core
import core::generic_thing as $thing  // import specific symbol
import utils version >= 2.0           // version constraint
```

Import statements appear at module level before object definitions.

## 11. Conversion Tools

The following tools convert between formats:

### moo-pack

Convert multi-file module to single file:
```
moo-pack mymodule/ > mymodule.moo
```

### moo-unpack

Convert single file to multi-file structure:
```
moo-unpack mymodule.moo mymodule/
```

### moo-compile

Convert source format to binary database:
```
moo-compile mymodule.moo -o mymodule.db
moo-compile database.moo -o database.db
```

### moo-decompile

Convert binary database to source format:
```
moo-decompile mymodule.db -o mymodule.moo
moo-decompile mymodule.db --unpack mymodule/
```

Options:
- `--module` - Output as module format (symbolic names)
- `--database` - Output as database format (object numbers)
- `--unpack <dir>` - Output as multi-file structure

## 12. External MOO Code Representation

Verb bodies use an "external" human-readable form that differs from the internal server representation. This provides a cleaner syntax for authoring while maintaining full compatibility.

### Comments

**External form:**
```
// This is a comment
// Another comment
x = 5;  // inline comment
```

**Internal form:**
```
"This is a comment";
"Another comment";
x = 5;
```

### Named Arguments

**External form:**
```
method greet(who, what, ?greeting = "Hello")
  player:tell(greeting + ", " + who + "!");
endmethod
```

**Internal form:**
The first line becomes an args unpacking statement:
```
{who, what, ?greeting = "Hello"} = args;
player:tell(greeting + ", " + who + "!");
```

### Named Loops

Named loops allow breaking or continuing outer loops (this is an existing MOO extension in some servers):

**External form:**
```
while outer (i < 10)
  while inner (j < 10)
    if (should_break)
      break outer;   // break out of outer loop
    endif
    if (should_skip)
      continue outer; // continue outer loop
    endif
  endwhile
endwhile

for item in (items)
  // loop body
endfor
```

These are preserved in both internal and external forms where supported.

### Control Structures

Standard MOO control structures are preserved as-is:

```
if (condition)
  // body
elseif (other_condition)
  // body
else
  // body
endif

while (condition)
  // body
endwhile

for x in (list)
  // body
endfor

for i in [1..10]
  // body
endfor

try
  // body
except e (E_PERM)
  // handler
finally
  // cleanup
endtry

fork (delay)
  // async body
endfork

fork name (delay)
  // named fork
endfork
```

## 13. Transformation Rules

### Externalize

Convert internal MOO code to external representation:

1. Replace string-statement comments with `//` comments
2. Extract leading `{...} = args;` to method signature
3. Preserve all other constructs

### Internalize

Convert external representation to internal MOO code:

1. Replace `//` comments with string statements
2. Convert method signature args to `{...} = args;` statement
3. Preserve all other constructs

### Round-Trip Safety

These transformations must be lossless:

```
internalize(externalize(code)) == code
externalize(internalize(code)) == code
```

With the following caveats:
- Whitespace may be normalized
- Comment style is converted (but content preserved)
- Semantically equivalent variations may be canonicalized

## 14. Complete Example

### Single Object

```
object @mail_recipient
  name "Mail Recipient"
  parent $thing
  owner $wizard
  flags fertile

  property mailbox readable = {}
  property max_mail = 100
  property mail_notify inherited = 1

  method receive_mail(sender, subject, body)
    // Receive a piece of mail
    if (length(this.mailbox) >= this.max_mail)
      return E_QUOTA;
    endif

    msg = ["from" -> sender, "subject" -> subject,
           "body" -> body, "time" -> time()];
    this.mailbox = {msg, @this.mailbox};

    if (this.mail_notify && is_player(this))
      this:tell("You have new mail from " + sender.name);
    endif

    return 1;
  endmethod

  command "read mail" none none none
    // Read mail for this recipient
    if (player != this)
      player:tell("You can't read someone else's mail.");
      return;
    endif

    for msg in (this.mailbox)
      player:tell("From: " + msg["from"].name);
      player:tell("Subject: " + msg["subject"]);
      player:tell(msg["body"]);
      player:tell("---");
    endfor
  endcommand
endobject
```

### Module with Multiple Objects

```
module mail_system
  version "1.0.0"
  requires core >= 1.0
  exports @mail_recipient, @mailroom

forward @mailroom

object @mail_recipient
  name "Mail Recipient Mixin"
  parent $thing

  property mailbox readable = {}
  property mailroom = @mailroom

  method receive_mail(sender, subject, body)
    return this.mailroom:deliver(this, sender, subject, body);
  endmethod
endobject

object @mailroom
  name "Central Mailroom"
  parent $thing

  property all_mailboxes = {}

  method deliver(recipient, sender, subject, body)
    // Central mail delivery with logging
    msg = ["to" -> recipient, "from" -> sender,
           "subject" -> subject, "body" -> body,
           "time" -> time()];
    recipient.mailbox = {msg, @recipient.mailbox};
    this.all_mailboxes = {msg, @this.all_mailboxes};
    return 1;
  endmethod
endobject

endmodule
```

## 15. Future Considerations

The following are not addressed in this RFC but may be considered in future revisions:

- **Macros/Templates**: Parameterized object definitions
- **Type Annotations**: Optional type hints for properties and verb arguments
- **Documentation Comments**: Structured doc comments for generating documentation
- **Conditional Compilation**: Platform-specific code sections
- **Binary Assets**: Embedding or referencing binary data

## 16. Appendix: Grammar Summary

```
file            := module | database | object+

module          := 'module' IDENT header* content* 'endmodule'
database        := 'database' db_header* object* 'enddatabase'

header          := version | requires | exports | import | include
db_header       := version | max_object | recycled

version         := 'version' STRING
requires        := 'requires' IDENT version_constraint?
exports         := 'exports' ref_list
import          := 'import' IDENT ('::' IDENT)? ('as' ref)?
include         := 'include' STRING

content         := object | forward
forward         := 'forward' LOCAL_REF

object          := 'object' ref object_body* 'endobject'
object_body     := name | owner | parent | location | flags
                 | property | method | command | object

name            := 'name' STRING
owner           := 'owner' ref
parent          := 'parent' ref
location        := 'location' ref
flags           := 'flags' FLAG+

property        := 'property' IDENT prop_mod
prop_mod        := FLAG* '=' value
                 | 'inherited' ('=' value)?
                 | 'clear'

method          := 'method' verb_name args? FLAG* code 'endmethod'
command         := 'command' STRING obj_spec PREP obj_spec FLAG* code 'endcommand'

verb_name       := IDENT | STRING
args            := '(' arg_list ')'
arg_list        := arg (',' arg)*
arg             := '?'? IDENT ('=' value)?

obj_spec        := 'this' | 'any' | 'none'
PREP            := 'none' | 'any' | 'with' | 'at' | 'to' | ...

ref             := OBJ_NUM | BUILTIN | SYMBOLIC | LOCAL_REF | QUALIFIED
OBJ_NUM         := '#' '-'? DIGITS
BUILTIN         := '$nothing' | '$ambiguous_match' | '$failed_match'
SYMBOLIC        := '$' IDENT
LOCAL_REF       := '@' IDENT
QUALIFIED       := IDENT '::' IDENT

value           := STRING | NUMBER | FLOAT | ref | list | map | ERROR
list            := '{' (value (',' value)*)? '}'
map             := '[' (map_entry (',' map_entry)*)? ']'
map_entry       := value '->' value

FLAG            := 'readable' | 'writable' | 'chown' | 'r' | 'w' | 'c'
                 | 'player' | 'programmer' | 'wizard' | 'fertile'
                 | 'executable' | 'x' | 'debug' | 'd' | 'wizardly'
                 | 'owner' ref | 'perms' STRING

code            := <MOO code in external representation>
```

## 17. References

- LambdaMOO Programmer's Manual
- MOO Database Format Documentation
- Existing MOO code decompilation tools
