import test from 'node:test';
import assert from 'node:assert/strict';
import { compilePpubsQuery, ppubsQueryTextEqual } from './cdp-cli.mjs';

test('PPS numeric history literal rewrite is explicit, without relaxing query binding', () => {
  for (const [q, number] of [['US20260233895A1','20260233895'],['US11401089B2','11401089'],['USD1111090S','D1111090']]) {
    const row = {q, strategy:'record_number'};
    assert.equal(compilePpubsQuery(row,'record_number').rendered_query, `${number}.PN.`);
    assert.equal(compilePpubsQuery({...row,query_compiler_revision:'ppubs-quoted-record-v1'},'record_number').rendered_query, `"${number}".PN.`);
  }
  assert.throws(() => compilePpubsQuery({q:'US11401089B2 OR 1', strategy:'record_number', query_compiler_revision:'ppubs-quoted-record-v1'},'record_number'));
});


test('PPS history binding preserves phrases and Boolean meaning across recorder and executor', async () => {
  const fs = await import('node:fs/promises');
  const cases = JSON.parse(await fs.readFile(new URL('../../fixtures/ppubs-query-equality.json', import.meta.url), 'utf8'));
  for (const [actual, expected, equal] of cases) assert.equal(ppubsQueryTextEqual(actual, expected), equal, JSON.stringify([actual, expected]));
});
