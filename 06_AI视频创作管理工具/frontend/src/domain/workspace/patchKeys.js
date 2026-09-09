/** Workspace patch field groups — mirrors backend domain endpoints. */

export const DOCUMENT_KEYS = [
  'documentText',
  'splitStrategy',
  'customSplitPattern',
  'durationMinutes',
  'activeSegmentId',
  'contentType',
  'scriptConvertTemplateId',
];

export const SEGMENT_KEYS = ['segments', 'clearDownstream'];

export const SCRIPT_KEYS = ['scripts', 'scriptValidation'];

export const SETTINGS_KEYS = [
  'expectedTotalDurationSeconds',
  'defaultAspectRatio',
  'defaultVideoDuration',
  'defaultVideoModel',
  'defaultResolution',
  'projectStylePrompt',
  'outputRoot',
  'sourceAssetsRoot',
  'dataRoot',
];

export const ASSET_KEYS = ['assetsConfirmed'];

function hasOwn(patch, key) {
  return Object.prototype.hasOwnProperty.call(patch, key);
}

export function pickPatchKeys(patch, keys) {
  return keys.reduce((acc, key) => {
    if (hasOwn(patch, key)) acc[key] = patch[key];
    return acc;
  }, {});
}

export function patchTouches(patch, keys) {
  return keys.some((key) => hasOwn(patch, key));
}

export function splitPatchByDomain(patch) {
  return {
    document: pickPatchKeys(patch, DOCUMENT_KEYS),
    segments: pickPatchKeys(patch, SEGMENT_KEYS),
    scripts: pickPatchKeys(patch, SCRIPT_KEYS),
    settings: pickPatchKeys(patch, SETTINGS_KEYS),
    assets: pickPatchKeys(patch, ASSET_KEYS),
  };
}
