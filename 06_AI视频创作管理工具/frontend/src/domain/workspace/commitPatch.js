/**
 * Commit workspace field patches to granular backend APIs.
 * The session is a client composition; each field is persisted through its typed endpoint.
 */

import {
  confirmAssets,
  replaceScripts,
  replaceSegments,
  saveDocument,
  saveProjectSettings,
  saveSegmentScript,
} from '../../api/workspace';
import { splitPatchByDomain } from './patchKeys';

function withRevision(revision, body) {
  return revision == null ? body : { ...body, revision };
}

async function commitDocumentPatch(projectId, workspace, patch, revision) {
  const payload = {};
  if ('documentText' in patch) payload.document_text = patch.documentText;
  if ('splitStrategy' in patch) payload.split_strategy = patch.splitStrategy;
  if ('customSplitPattern' in patch) payload.custom_split_pattern = patch.customSplitPattern;
  if ('durationMinutes' in patch) payload.duration_minutes = patch.durationMinutes;
  if ('activeSegmentId' in patch) payload.active_segment_id = patch.activeSegmentId;
  if ('contentType' in patch) payload.content_type = patch.contentType;
  if ('scriptConvertTemplateId' in patch) payload.script_convert_template_id = patch.scriptConvertTemplateId;
  if (!Object.keys(payload).length) return workspace;
  return saveDocument(projectId, withRevision(revision, payload));
}

async function commitSegmentsPatch(projectId, workspace, patch, revision) {
  return replaceSegments(
    projectId,
    withRevision(revision, {
      segments: patch.segments ?? workspace.segments ?? [],
      active_segment_id: patch.activeSegmentId ?? workspace.activeSegmentId,
      clear_downstream: Boolean(patch.clearDownstream),
    }),
  );
}

async function commitScriptsPatch(projectId, workspace, patch, revision) {
  const scripts = patch.scripts ?? workspace.scripts ?? {};
  const scriptValidation = patch.scriptValidation ?? workspace.scriptValidation ?? {};
  const segmentIds = Object.keys(scripts);
  if (!segmentIds.length && !Object.keys(scriptValidation).length) return workspace;

  // Single-segment inline edit: use per-segment endpoint (lighter, lock-aware).
  if (
    segmentIds.length === 1 &&
    !('scriptValidation' in patch && Object.keys(patch.scriptValidation || {}).length > 1)
  ) {
    const segmentId = segmentIds[0];
    return saveSegmentScript(
      projectId,
      segmentId,
      withRevision(revision, {
        content: scripts[segmentId] ?? '',
        validation: scriptValidation[segmentId] ?? {},
      }),
    );
  }

  return replaceScripts(
    projectId,
    withRevision(revision, {
      scripts,
      script_validation: scriptValidation,
    }),
  );
}

async function commitSettingsPatch(projectId, patch, revision) {
  const payload = {};
  if ('expectedTotalDurationSeconds' in patch) {
    payload.expected_total_duration_seconds = patch.expectedTotalDurationSeconds;
  }
  if ('defaultAspectRatio' in patch) payload.default_aspect_ratio = patch.defaultAspectRatio;
  if ('defaultVideoDuration' in patch) payload.default_video_duration = patch.defaultVideoDuration;
  if ('defaultVideoModel' in patch) payload.default_video_model = patch.defaultVideoModel;
  if ('defaultResolution' in patch) payload.default_resolution = patch.defaultResolution;
  if ('projectStylePrompt' in patch) payload.project_style_prompt = patch.projectStylePrompt;
  if ('outputRoot' in patch) payload.output_root = patch.outputRoot;
  if ('sourceAssetsRoot' in patch) payload.source_assets_root = patch.sourceAssetsRoot;
  if ('dataRoot' in patch) payload.data_root = patch.dataRoot;
  if (!Object.keys(payload).length) return null;
  return saveProjectSettings(projectId, withRevision(revision, payload));
}

async function commitAssetsPatch(projectId, patch) {
  if (!('assetsConfirmed' in patch)) return null;
  return confirmAssets(projectId, Boolean(patch.assetsConfirmed));
}

/**
 * Apply a workspace patch through the correct domain API(s), in stable order.
 * Returns the latest server workspace view.
 */
export async function commitWorkspacePatch(projectId, workspace, patch) {
  if (!projectId || !patch || !Object.keys(patch).length) {
    return workspace;
  }

  const groups = splitPatchByDomain(patch);
  let current = workspace;
  let revision = workspace?.revision;

  if (Object.keys(groups.document).length) {
    current = await commitDocumentPatch(projectId, current, groups.document, revision);
    revision = current?.revision;
  }
  if (Object.keys(groups.segments).length) {
    current = await commitSegmentsPatch(projectId, current, groups.segments, revision);
    revision = current?.revision;
  }
  if (Object.keys(groups.scripts).length) {
    current = await commitScriptsPatch(projectId, current, groups.scripts, revision);
    revision = current?.revision;
  }
  if (Object.keys(groups.settings).length) {
    const saved = await commitSettingsPatch(projectId, groups.settings, revision);
    if (saved) {
      current = saved;
      revision = current?.revision;
    }
  }
  if (Object.keys(groups.assets).length) {
    const saved = await commitAssetsPatch(projectId, groups.assets);
    if (saved) {
      current = saved;
    }
  }

  return current;
}
