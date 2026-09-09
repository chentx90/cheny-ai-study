import { describe, expect, it } from 'vitest';
import { readRouteState, routeForState } from './routeState';

describe('route state', () => {
  it('reads project view from URL', () => {
    expect(readRouteState({ pathname: '/projects/proj_1/video' })).toEqual({
      view: 'video',
      projectId: 'proj_1',
    });
  });

  it('falls back to project hub for unknown path', () => {
    expect(readRouteState({ pathname: '/anything' })).toEqual({ view: 'projects', projectId: '' });
  });

  it('writes settings and project routes', () => {
    expect(routeForState('settings')).toBe('/settings');
    expect(routeForState('resources', 'proj_1')).toBe('/projects/proj_1/resources');
  });
});

