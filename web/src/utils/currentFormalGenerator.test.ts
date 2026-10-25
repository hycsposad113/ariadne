import { describe, it, expect } from 'vitest';
import { currentFormalProposals } from './currentFormalGenerator';
describe('current multimodal Compare version', () => {
  it('keeps v7 and preserves v6 records outside the listing', () => {
    const rows = [{ id: 'old', generator_version: 'formal-dictionary-v6-south-strip-collector' }, { id: 'new', generator_version: 'formal-dictionary-v7-multimodal' }, { id: 'unknown' }];
    expect(currentFormalProposals(rows).map(row => row.id)).toEqual(['new']);
    expect(rows).toHaveLength(3);
  });
});
