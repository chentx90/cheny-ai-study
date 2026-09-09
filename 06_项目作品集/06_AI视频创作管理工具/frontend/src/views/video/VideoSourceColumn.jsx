import React, { useMemo } from 'react';
import { BookOpen, Clapperboard, Download } from 'lucide-react';
import Empty from '../../components/Empty';
import EpisodePicker from '../../components/EpisodePicker';
import FontSizeControls from '../../components/FontSizeControls';
import PanelTitle from '../../components/PanelTitle';
import { downloadTextFile, sanitizeFilename } from '../../utils/download';
import SubjectAssetThumb, { buildAssetUrl, missingAsset } from './SubjectAssetThumb';
import {
  cardAssetPaths,
  defaultEpisodeTitle,
  MAX_PROMPT_CONTENT_FONT_SIZE,
  MIN_PROMPT_CONTENT_FONT_SIZE,
} from './videoViewUtils';

export default function VideoSourceColumn({
  workspace,
  activeSegment,
  activeSegmentIndex,
  activeScript,
  selectedEntityCards,
  projectName,
  assets = [],
  selectedProject,
  apiBase,
  setActiveSegment,
  scriptFontSize = 14,
  setScriptFontSize,
}) {
  const assetByPath = useMemo(
    () => new Map((assets || []).map((asset) => [asset.path, asset])),
    [assets],
  );
  const episodeTitle = activeSegment
    ? activeSegment.title || `第${activeSegmentIndex + 1}集`
    : '分集';
  const projectPrefix = sanitizeFilename(projectName || 'project', 'project');

  function downloadScript() {
    downloadTextFile(activeScript || '', `${projectPrefix}-${sanitizeFilename(episodeTitle, '分集')}-剧本`);
  }

  return (
    <section className="video-source-column">
      <article className="panel video-left-card video-script-card">
        <PanelTitle
          icon={BookOpen}
          title={
            <EpisodePicker
              segments={workspace.segments}
              activeSegmentId={activeSegment?.id}
              onSelect={setActiveSegment}
              getLabel={(segment, index) => defaultEpisodeTitle(segment, index)}
            />
          }
        >
          <div className="video-script-panel-actions">
            <button type="button" className="secondary" disabled={!activeScript?.trim()} onClick={downloadScript}>
              <Download />
              下载剧本
            </button>
            <FontSizeControls
              value={scriptFontSize}
              min={MIN_PROMPT_CONTENT_FONT_SIZE}
              max={MAX_PROMPT_CONTENT_FONT_SIZE}
              onChange={setScriptFontSize}
            />
            <span className="panel-count-pill">{activeScript.length} 字</span>
          </div>
        </PanelTitle>
        <div
          className="video-script-viewer video-content-scalable"
          style={{ '--content-text-size': `${scriptFontSize}px` }}
        >
          <textarea
            value={activeScript}
            readOnly
            placeholder="当前集暂无剧本原文"
          />
        </div>
      </article>

      <article className="panel video-left-card video-entity-card-section">
        <PanelTitle icon={Clapperboard} title="相关实体卡片" />
        <div className={`video-entity-list ${selectedEntityCards.length === 0 ? 'is-empty' : 'mention-ref-list video-entity-ref-list'}`}>
          {selectedEntityCards.length === 0 && <Empty text="暂无匹配实体卡片" />}
          {selectedEntityCards.map((card) => {
            const paths = cardAssetPaths(card);
            const firstAsset = paths.map((path) => assetByPath.get(path) || missingAsset(path))[0];
            return (
              <article className="mention-ref-item" key={card.id}>
                <span className="mention-ref-thumb">
                  {firstAsset ? (
                    <SubjectAssetThumb
                      asset={firstAsset}
                      url={buildAssetUrl(apiBase, selectedProject, firstAsset)}
                    />
                  ) : (
                    <span>无素材</span>
                  )}
                </span>
                <span className="mention-ref-meta">
                  <strong>{card.entity_name}</strong>
                  {card.state ? <em>{card.state}</em> : null}
                </span>
              </article>
            );
          })}
        </div>
      </article>
    </section>
  );
}
