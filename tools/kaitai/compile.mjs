// Compile a Kaitai Struct description to Python.
//
// Usage: node compile.mjs SOURCE.ksy OUTPUT.py
//
// Run `npm install` in this directory first. The JavaScript build of the
// compiler needs no Java.
import { readFileSync, writeFileSync } from 'node:fs';
import yaml from 'js-yaml';
import KaitaiStructCompiler from 'kaitai-struct-compiler';

const [source, output] = process.argv.slice(2);
if (!source || !output) {
  console.error('usage: node compile.mjs SOURCE.ksy OUTPUT.py');
  process.exit(2);
}
const ksy = yaml.load(readFileSync(source, 'utf8'));
const files = await KaitaiStructCompiler.compile('python', ksy, null, false);
const names = Object.keys(files);
if (names.length !== 1) {
  console.error(`expected one generated file, got ${names.join(', ')}`);
  process.exit(1);
}
writeFileSync(output, files[names[0]]);
