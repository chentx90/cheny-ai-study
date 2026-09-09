import React from 'react';
import { ImageIcon, Music2 } from 'lucide-react';

export const assetUploadAccept = 'image/*,audio/*,video/*';

export const assetFilters = [
  { id: 'all', label: '全部素材' },
  { id: 'image', label: '图片' },
  { id: 'audio', label: '音频' },
  { id: 'video', label: '视频' },
];

export function formatAssetSize(bytes = 0) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

export function buildAssetUrl(apiBase, selectedProject, asset) {
  if (!selectedProject || !asset?.path) return '';
  const encodedPath = asset.path.split('/').map(encodeURIComponent).join('/');
  return `${apiBase}/api/projects/${selectedProject.id}/assets/${encodedPath}`;
}

export function AssetPreview({ asset, url, large = false }) {
  if (asset.asset_type === 'image') {
    return <img className={large ? 'asset-preview-media' : 'asset-thumb-media'} src={url} alt={asset.filename} />;
  }
  if (asset.asset_type === 'video') {
    return large ? <video className="asset-preview-media" src={url} controls /> : <video className="asset-thumb-media" src={url} muted preload="metadata" />;
  }
  if (asset.asset_type === 'audio') {
    return large ? <audio className="asset-preview-audio" src={url} controls /> : <span className="asset-thumb-placeholder"><Music2 />音频</span>;
  }
  return <span className="asset-thumb-placeholder"><ImageIcon />素材</span>;
}
