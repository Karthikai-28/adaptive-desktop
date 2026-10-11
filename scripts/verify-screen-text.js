#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const M = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../shell/adaptive-shell@local/screenTextModel.js'), 'utf8') +
    '\nObject.assign(out, {parseTsv, mapWords, hitWord, passage, lineWords, selectionText});', {out: M});
const row = (text, block, line, word, x = 10) => `5\t1\t${block}\t1\t${line}\t${word}\t${x}\t20\t40\t20\t95\t${text}`;
const tsv = [row('second', 1, 1, 2, 60), row('first', 1, 1, 1), row('next', 1, 2, 1),
    row('block', 2, 1, 1), 'level\tpage_num', '1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t',
    row('', 1, 1, 3), row('bad', 1, 1, 3).replace('\t95\t', '\tNaN\t'),
    row('invalid', 1, 1, 3).replace('\t40\t20\t', '\t0\t20\t')].join('\n');
const words = M.parseTsv(tsv);
assert.equal(words.length, 4);
assert.equal(M.selectionText(words, [0, 1, 2, 3]), 'first second\nnext\n\nblock');
assert.equal(JSON.stringify(M.passage(words, 2, 0)), '[0,1,2]');
assert.equal(JSON.stringify(M.passage(words, 0, 2)), '[0,1,2]');
assert.equal(JSON.stringify(M.passage(words, 0, 3)), '[]');
assert.equal(JSON.stringify(M.lineWords(words, 1)), '[0,1]');
assert.equal(M.selectionText(words, [2, 0, 0, 999]), 'first\nnext');
assert.equal(M.selectionText(words, []), '');
assert.equal(M.passage(words, -1, 0).length, 0);
const mapped = M.mapWords(words, 200, 100, { x: -1000, y: 300, width: 100, height: 50 });
assert.equal(mapped[0].x, -995);
assert.equal(mapped[0].y, 310);
assert.equal(mapped[0].width, 20);
assert.equal(M.hitWord(mapped, -994, 315), 0);
assert.equal(M.hitWord(mapped, 0, 0), -1);
assert.equal(M.mapWords(words, 0, 100, {}).length, 0);
assert.equal(M.mapWords(words, 20, 100, {x:0,y:0,width:20,height:100}).length, 0);
const other = M.parseTsv(row('monitor two', 1, 1, 1), 1);
assert.equal(M.passage([...words, ...other], 0, 4).length, 0);
console.log('OK screen text: TSV validation, reading order, forward/reverse selection, line selection, clipboard text, monitor offsets and scaling');
