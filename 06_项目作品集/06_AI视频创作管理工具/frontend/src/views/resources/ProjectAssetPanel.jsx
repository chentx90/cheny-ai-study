import React from 'react';
import { Database, Download, Edit3, Eye, Loader2, Save, Trash2, Upload, X } from 'lucide-react';

import Empty from '../../components/Empty';
import PanelTitle from '../../components/PanelTitle';
import { assetTypeLabel } from '../../utils';
import { AssetPreview, assetFilters, assetUploadAccept, buildAssetUrl, formatAssetSize } from './resourceMedia';

export default function ProjectAssetPanel({
  assets, filteredAssets, assetFilter, setAssetFilter, assetSearch, setAssetSearch,
  uploadBusy, handleProjectAssetUpload, apiBase, selectedProject, setPreviewAsset,
  renameTargetPath, renameDraft, setRenameDraft, setRenameTargetPath, submitRename,
  beginRename, busy, downloadingPath, handleDownloadAsset, deleteAsset,
}) {
  return (
    <section className="panel asset-library-panel">
      <PanelTitle icon={Database} title="项目素材">
        <select className="asset-filter-select" value={assetFilter} onChange={(event) => setAssetFilter(event.target.value)}>
          {assetFilters.map((filter) => <option value={filter.id} key={filter.id}>{filter.label}</option>)}
        </select>
        <input className="asset-search-input" value={assetSearch} onChange={(event) => setAssetSearch(event.target.value)} placeholder="筛选素材" />
        <label className={`upload-control ${uploadBusy ? 'is-disabled' : ''}`}>
          {uploadBusy ? <Loader2 className="spin" /> : <Upload />}导入素材
          <input type="file" accept={assetUploadAccept} multiple disabled={uploadBusy} onChange={handleProjectAssetUpload} />
        </label>
      </PanelTitle>
      <div className="asset-card-grid">
        {filteredAssets.length === 0 && <Empty text={assets.length === 0 ? '暂无项目素材' : '没有符合筛选的素材'} />}
        {filteredAssets.map((asset) => {
          const url = buildAssetUrl(apiBase, selectedProject, asset);
          const isRenaming = renameTargetPath === asset.path;
          const isRenamingBusy = busy.has(`renameAsset:${asset.path}`);
          const isDownloading = downloadingPath === asset.path;
          return (
            <article className="asset-card" key={asset.path}>
              <button type="button" className="asset-thumb-button" title="查看素材" onClick={() => setPreviewAsset(asset)}><AssetPreview asset={asset} url={url} /></button>
              <div className="asset-card-meta">
                <div className="asset-card-meta-main">
                  {isRenaming ? <input value={renameDraft} onChange={(event) => setRenameDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') submitRename(asset); if (event.key === 'Escape') setRenameTargetPath(''); }} /> : <><strong>{asset.filename}</strong><small>{assetTypeLabel(asset.asset_type)} · {formatAssetSize(asset.bytes)}</small></>}
                </div>
                {!isRenaming && <button type="button" className="asset-card-meta-delete danger icon-button" title="删除素材" onClick={() => deleteAsset(asset)}><Trash2 /></button>}
              </div>
              <div className={`asset-card-actions ${isRenaming ? 'is-renaming' : ''}`}>
                {isRenaming ? <><button type="button" className="secondary" disabled={isRenamingBusy} onClick={() => submitRename(asset)}>{isRenamingBusy ? <Loader2 className="spin" /> : <Save />}保存</button><button type="button" className="secondary" disabled={isRenamingBusy} onClick={() => setRenameTargetPath('')}><X />取消</button></> : <><button type="button" className="secondary" onClick={() => setPreviewAsset(asset)}><Eye />查看</button><button type="button" className="secondary" disabled={isDownloading} onClick={() => handleDownloadAsset(asset)}>{isDownloading ? <Loader2 className="spin" /> : <Download />}下载</button><button type="button" className="secondary" onClick={() => beginRename(asset)}><Edit3 />重命名</button></>}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
