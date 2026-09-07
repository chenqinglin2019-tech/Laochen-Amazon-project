import test from 'node:test';
import assert from 'node:assert/strict';
import { compilePpubsQuery } from './cdp-cli.mjs';

test('PPS numeric history literal rewrite is explicit, without relaxing query binding', () => {
  for (const [q, number] of [['US20260233895A1','20260233895'],['US11401089B2','11401089'],['USD1111090S','D1111090']]) {
    const row = {q, strategy:'record_number'};
    assert.equal(compilePpubsQuery(row,'record_number').rendered_query, `${number}.PN.`);
    assert.equal(compilePpubsQuery({...row,query_compiler_revision:'ppubs-quoted-record-v1'},'record_number').rendered_query, `"${number}".PN.`);
  }
  assert.throws(() => compilePpubsQuery({q:'US11401089B2 OR 1', strategy:'record_number', query_compiler_revision:'ppubs-quoted-record-v1'},'record_number'));
});
