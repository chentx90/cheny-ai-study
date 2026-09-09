export function categoryLabel(category) {
  return { active: '进行中', draft: '草稿', archive: '归档' }[category] || '未分类';
}

export function typeLabel(type) {
  return { character: '人物', prop: '物品', scene: '场景' }[type] || type;
}

export function assetTypeLabel(type) {
  return { image: '图片', audio: '音频', video: '视频' }[type] || type;
}

export function strategyLabel(strategy) {
  return {
    chapter: '章节切分',
    custom_regex: '自定义正则',
    manual: '手动标记',
    length: '长度切分',
    duration: '按时长切分',
    duration_2min: '按时长切分',
  }[strategy] || strategy;
}

export function statusLabel(status) {
  return { pass: '通过', warn: '警告', fail: '失败' }[status] || status;
}

export function scriptStatusLabel(meta, hasOutput = false) {
  if (meta?.confirmed) return '已确认';
  if (meta?.status === 'failed') return '失败';
  if (meta?.status === 'invalid') return '不合格';
  if (meta?.status === 'edited') return '已编辑';
  if (meta?.status === 'imported') return '已导入';
  if (meta?.status === 'script') return '已是剧本';
  if (meta?.status === 'converted') return '已转换';
  return hasOutput ? '已完成' : '未处理';
}

export function requireProjectAndSegments(workspace, project) {
  if (!project) throw new Error('请先选择项目');
  if (workspace.segments.length === 0) throw new Error('请先完成文本切分');
}
