import React from 'react';
import { Box, ImageIcon, Music2, Video } from 'lucide-react';

export function buildAssetUrl(apiBase, selectedProject, asset) {
  if (!selectedProject?.id || !asset?.path || asset.missing) return '';
  const encodedPath = asset.path.split('/').map(encodeURIComponent).join('/');
  return `${apiBase || ''}/api/projects/${encodeURIComponent(selectedProject.id)}/assets/${encodedPath}`;
}

export function missingAsset(path) {
  const lower = String(path || '').toLowerCase();
  const assetType = lower.includes('/audio/') ? 'audio' : lower.includes('/videos/') ? 'video' : 'image';
  return {
    path,
    filename: String(path || '').split('/').pop() || path || '素材缺失',
    asset_type: assetType,
    bytes: 0,
    missing: true,
  };
}

export function formatAssetSize(bytes = 0) {
  if (!bytes) return '未知大小';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

export default function SubjectAssetThumb({ asset, url, large = false }) {
  if (!asset || asset.missing) {
    return (
      <span className={large ? 'subject-asset-placeholder large' : 'subject-asset-placeholder'}>
        <ImageIcon />
        缺失
      </span>
    );
  }
  if (asset.asset_type === 'image') {
    return <img className={large ? 'subject-asset-preview-media' : 'subject-asset-thumb-media'} src={url} alt={asset.filename} />;
  }
  if (asset.asset_type === 'video') {
    return large ? (
      <video className="subject-asset-preview-media" src={url} controls />
    ) : (
      <span className="subject-asset-placeholder">
        <Video />
        视频
      </span>
    );
  }
  if (asset.asset_type === 'audio') {
    return large ? (
      <audio className="subject-asset-preview-audio" src={url} controls />
    ) : (
      <span className="subject-asset-placeholder">
        <Music2 />
        音频
      </span>
    );
  }
  return (
    <span className={large ? 'subject-asset-placeholder large' : 'subject-asset-placeholder'}>
      <Box />
      素材
    </span>
  );
}
