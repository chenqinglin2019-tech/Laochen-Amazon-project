import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confirmedAmazonVariant } from './cdp-cli.mjs';

test('first valid child can differ from requested parent, but frozen target cannot change', () => {
  const task = { product_entry_revision: 'dual-entry-v1', request: { entry_type: 'amazon_url' },
    product: { requested_asin: 'B000000001' }, product_identity: { status: 'pending' } };
  const variant = confirmedAmazonVariant(task, 'B000000002', 'Black');
  assert.equal(variant.confirmed, true);
  task.product_identity = { status: 'frozen', binding: { asin: 'B000000002', variant } };
  assert.deepEqual(confirmedAmazonVariant(task, 'B000000002', 'Black'), variant);
  assert.throws(() => confirmedAmazonVariant(task, 'B000000003', 'White'), /FROZEN_TARGET/);
  assert.throws(() => confirmedAmazonVariant(task, 'B000000002', 'White'), /FROZEN_TARGET/);
});
test('legacy equality stays unchanged and user materials cannot enter Amazon capture', () => {
  assert.equal(confirmedAmazonVariant({ product: { requested_asin: 'B000000001' } }, 'B000000002', '').confirmed, false);
  assert.throws(() => confirmedAmazonVariant({ product_entry_revision: 'dual-entry-v1',
    request: { entry_type: 'user_materials' } }, 'B000000001', ''), /CONTRACT_INVALID/);
});
test('an explicit target change review permits only its named child and variant', () => {
  const task = { product_entry_revision: 'dual-entry-v1', request: { entry_type: 'amazon_url' },
    product: { requested_asin: 'B000000001' },
    product_identity: { status: 'frozen', sha256: 'old-target', binding: {
      asin: 'B000000002', variant: { label: 'Selected option', value: 'Black', confirmed: true } } } };
  const review = { kind: 'target_change', expected_target_sha256: 'old-target', actual_asin: 'B000000003',
    variant: { label: 'Selected option', value: 'White', confirmed: true },
    reason: 'Seller changed the target.', user_statement: 'Use the white child.' };
  assert.deepEqual(confirmedAmazonVariant(task, 'B000000003', 'White', review), review.variant);
  assert.throws(() => confirmedAmazonVariant(task, 'B000000004', 'White', review), /FROZEN_TARGET/);
  assert.throws(() => confirmedAmazonVariant(task, 'B000000003', 'Black', review), /FROZEN_TARGET/);
  assert.throws(() => confirmedAmazonVariant(task, 'B000000003', 'White', { ...review, user_statement: '' }), /FROZEN_TARGET/);
});
