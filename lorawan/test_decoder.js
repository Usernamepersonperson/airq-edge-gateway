// Run with: node lorawan/test_decoder.js
// No dependencies. The vectors are shared with the Python encoder test.
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { decodeUplink } = require("./decoder.js");
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "test_vectors.json"), "utf8"));
const schema = JSON.parse(fs.readFileSync(path.join(__dirname, "data.schema.json"), "utf8"));

const toBytes = (hex) => hex.match(/../g).map((h) => parseInt(h, 16));

for (const v of vectors) {
  const res = decodeUplink({ bytes: toBytes(v.hex), fPort: 1 });
  assert.deepStrictEqual(res.errors, [], `${v.name}: no errors`);
  assert.deepStrictEqual(res.data, v.expected, v.name);
  // Every required schema key must be present in the decoded data.
  assert.deepStrictEqual(Object.keys(res.data).sort(), [...schema.required].sort());
  console.log(`ok - ${v.name}`);
}

for (const bad of [[], [0x08, 0xca], new Array(13).fill(0)]) {
  const res = decodeUplink({ bytes: bad });
  assert.strictEqual(res.errors.length, 1, "wrong length reports an error");
  assert.deepStrictEqual(res.data, {});
}
console.log("ok - wrong lengths rejected");
console.log(`${vectors.length + 1} checks passed`);
