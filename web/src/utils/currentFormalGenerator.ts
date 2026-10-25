/** Compare shows the current generation contract; historical records stay stored. */
export const CURRENT_FORMAL_GENERATOR = 'formal-dictionary-v7-multimodal';
export function currentFormalProposals<T extends { generator_version?: string }>(rows: T[]): T[] {
  return rows.filter(row => row.generator_version === CURRENT_FORMAL_GENERATOR);
}
