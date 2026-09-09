export function agentMutationEvent(response) {
  const run = response?.run;
  const results = Array.isArray(run?.state?.results) ? run.state.results : [];
  const effectSet = new Set();
  const commands = [];
  const operationIds = [];
  let projectId = String(response?.thread?.project_id || '');

  results.forEach((result) => {
    if (!result?.ok || !Array.isArray(result.effects) || result.effects.length === 0) return;
    result.effects.forEach((effect) => effectSet.add(String(effect)));
    if (result.command) commands.push(String(result.command));
    if (result.operation_id) operationIds.push(String(result.operation_id));
    if (!projectId && result.project_id) projectId = String(result.project_id);
  });

  const effects = [...effectSet];
  if (!effects.length) return null;
  return {
    id: `${run?.id || 'run'}:${operationIds.join(',') || commands.join(',')}`,
    projectId,
    commands,
    effects,
  };
}
