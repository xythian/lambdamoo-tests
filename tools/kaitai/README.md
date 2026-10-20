# Session protocol description

`session_protocol.ksy` is a copy of the [Kaitai Struct](https://kaitai.io/)
description in wp-lambdamoo, which is normative for the session protocol's
byte layouts. `lib/session_protocol.py` is generated from it, and
`lib/session.py` checks every frame the server sends, and every frame the
reference edge sends, against it.

When the description changes in wp-lambdamoo, copy it here and regenerate:

```bash
cp ../wp-lambdamoo/session_protocol.ksy tools/kaitai/
cd tools/kaitai
npm install
node compile.mjs session_protocol.ksy ../../lib/session_protocol.py
```

The compiler is the JavaScript build, so this needs Node but not Java. Only
the generated Python and the `kaitaistruct` runtime are needed to run tests.
