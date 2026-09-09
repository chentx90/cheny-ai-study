import { describe, expect, it } from 'vitest';

import { agentMutationEvent } from './commandEffects';

describe('agentMutationEvent', () => {
  it('merges effects from completed command results', () => {
    const event = agentMutationEvent({
      thread: { project_id: 'project-a' },
      run: {
        id: 'run-a',
        state: {
          results: [
            { ok: true, command: 'visual-style.save', operation_id: 'op-1', effects: ['asset-production', 'projects'] },
            { ok: true, command: 'entity.adopt-image', operation_id: 'op-2', effects: ['entities', 'asset-production'] },
          ],
        },
      },
    });

    expect(event).toEqual({
      id: 'run-a:op-1,op-2',
      projectId: 'project-a',
      commands: ['visual-style.save', 'entity.adopt-image'],
      effects: ['asset-production', 'projects', 'entities'],
    });
  });

  it('ignores read-only and failed results', () => {
    expect(agentMutationEvent({ run: { state: { results: [
      { ok: true, command: 'script.show', effects: [] },
      { ok: false, command: 'visual-style.save', effects: ['asset-production'] },
    ] } } })).toBeNull();
  });
});
