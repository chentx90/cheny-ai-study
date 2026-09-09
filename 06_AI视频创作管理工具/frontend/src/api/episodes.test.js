import { describe, expect, it } from 'vitest';
import { episodesToWorkspaceFields } from './episodes';

describe('episode workspace adapter', () => {
  it('orders episodes and maps source and script fields', () => {
    const mapped = episodesToWorkspaceFields([
      { id: 'ep_2', order: 2, title: '第二集', source_text: '二', script_text: '' },
      {
        id: 'ep_1',
        order: 1,
        title: '第一集',
        source_text: '一',
        script_text: '场景：室内',
        script_validation: { status: 'edited' },
      },
    ]);
    expect(mapped.segments.map((item) => item.id)).toEqual(['ep_1', 'ep_2']);
    expect(mapped.scripts).toEqual({ ep_1: '场景：室内' });
    expect(mapped.scriptValidation.ep_1.status).toBe('edited');
  });
});
