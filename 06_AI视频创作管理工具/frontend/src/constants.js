import { Boxes, Film, Scissors, UsersRound, WandSparkles } from 'lucide-react';

export const defaultExpectedTotalDurationSeconds = 60;

export const promptCardMaxDurationSeconds = 15;

export const videoDurationMinSeconds = 4;
export const videoDurationMaxSeconds = 15;

export const videoRequestSettingsStorageKey = 'ai-video-manager:video-request-settings:v1';
export const videoRequestSettingsStoragePrefix = 'ai-video-manager:video-request-settings:';

export const defaultVideoRequestSettings = {
  model: '',
  customModel: '',
  aspectRatio: '9:16',
  duration: 5,
  resolution: '720p',
  referenceMode: 'omni',
  generateAudio: true,
  firstFrame: '',
  lastFrame: '',
  referenceImages: [],
  referenceVideos: [],
  referenceAudios: [],
};

/** 小云雀 CLI 独立默认值（与网关模型/参数隔离） */
export const defaultXyqVideoRequestSettings = {
  ...defaultVideoRequestSettings,
  model: 'Seedance_2.0_mini_lite',
  customModel: '',
  aspectRatio: '9:16',
  duration: 5,
  resolution: '720p',
  referenceMode: 'omni',
  generateAudio: true,
};

export const videoReferenceModeOptions = [
  { value: 'none', label: '无参考（纯提示词）' },
  { value: 'first_last', label: '首尾帧 F/L' },
  { value: 'multi', label: '多图 Multi' },
  { value: 'omni', label: 'Omni 多模态' },
];

export const videoModelOptions = [
  { value: '', label: '服务默认' },
  { value: 'kling-v2.1', label: 'Kling v2.1' },
  { value: 'kling-v2.1-master', label: 'Kling v2.1 Master' },
  { value: 'seedance-v1-pro', label: 'Seedance v1 Pro' },
  { value: 'veo3-fast', label: 'Veo 3 Fast' },
  { value: 'wan2.1', label: 'Wan 2.1' },
  { value: '__custom__', label: '自定义模型 ID' },
];

/** 小云雀 CLI 内置模型（provider=xyq 时使用，不拉网关 /models） */
export const xyqVideoModelOptions = [
  { value: 'Seedance_2.0_mini_lite', label: 'Seedance 2.0 Mini Lite（普通用户）' },
  { value: 'Seedance_2.0_mini', label: 'Seedance 2.0 Mini（VIP）' },
  { value: 'seedance2.0_vision', label: 'Seedance 2.0 Vision（VIP）' },
  { value: 'seedance2.0_fast_vision', label: 'Seedance 2.0 Fast Vision（VIP）' },
  { value: '__custom__', label: '手动输入模型 ID' },
];

export function isXyqVideoProvider(provider = '') {
  const value = String(provider || '').trim().toLowerCase();
  return value === 'xyq' || value === 'xiaoyunque' || value === 'pippit';
}

export const videoAspectRatioOptions = [
  { value: '9:16', label: '9:16 竖屏' },
  { value: '16:9', label: '16:9 横屏' },
  { value: '1:1', label: '1:1 方形' },
  { value: '4:3', label: '4:3 标准' },
  { value: '3:4', label: '3:4 竖幅' },
  { value: '21:9', label: '21:9 宽银幕' },
];

/** 小云雀 CLI 文档支持的比例（generate-video --ratio） */
export const xyqVideoAspectRatioOptions = [
  { value: '9:16', label: '9:16 竖屏' },
  { value: '16:9', label: '16:9 横屏' },
  { value: '3:4', label: '3:4 竖幅' },
  { value: '4:3', label: '4:3 标准' },
];

export const videoDurationOptions = Array.from(
  { length: videoDurationMaxSeconds - videoDurationMinSeconds + 1 },
  (_, index) => {
    const value = videoDurationMinSeconds + index;
    return { value, label: `${value} 秒` };
  },
);

export const videoResolutionOptions = [
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
  { value: '2k', label: '2K' },
  { value: '4k', label: '4K' },
];

/** 小云雀 CLI 文档支持的分辨率（generate-video --resolution） */
export const xyqVideoResolutionOptions = [
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
];

export const emptyProjectDraft = {
  name: '新视频项目',
  category: 'active',
  description: '',
  dataRoot: '',
  outputRoot: '',
  sourceAssetsRoot: '',
};

export const emptyWorkspace = {
  documentText: '',
  splitStrategy: 'chapter',
  customSplitPattern: '',
  durationMinutes: 2,
  segments: [],
  activeSegmentId: '',
  contentType: '分集原文',
  scriptConvertTemplateId: '',
  projectStylePrompt: '',
  scripts: {},
  scriptValidation: {},
  entities: [],
  prompts: {},
  expectedTotalDurationSeconds: null,
  defaultAspectRatio: '9:16',
  defaultVideoDuration: 5,
  defaultVideoModel: '',
  defaultResolution: '720p',
  outputRoot: '',
  sourceAssetsRoot: '',
  dataRoot: '',
};

export const navItems = [
  { id: 'projects', label: '项目管理', icon: Boxes },
  { id: 'preprocess', label: '预处理', icon: Scissors },
  { id: 'resources', label: '资源管理', icon: UsersRound },
  { id: 'video', label: '视频生成', icon: Film },
  { id: 'prompts', label: '提示词管理', icon: WandSparkles },
];

export const imageRequestSettingsStorageKey = 'ai-video-manager:image-request-settings:v1';

export const defaultImageRequestSettings = {
  model: '',
  size: '1024x1024',
  parallelCount: 1,
};

export const imageSizeOptions = [
  { value: '1024x1024', label: '1024×1024 方形' },
  { value: '1024x1536', label: '1024×1536 竖图' },
  { value: '1536x1024', label: '1536×1024 横图' },
  { value: '512x512', label: '512×512 小图' },
  { value: '768x1344', label: '768×1344 竖屏' },
  { value: '1344x768', label: '1344×768 横屏' },
];

export const imageModelPresets = [
  { value: 'gpt-image-1', label: 'gpt-image-1' },
  { value: 'dall-e-3', label: 'dall-e-3' },
  { value: 'flux', label: 'flux' },
  { value: '__custom__', label: '手动输入模型 ID' },
];

export const promptCategories = [
  { id: 'split_planning', label: 'AI 切分建议' },
  { id: 'script_convert', label: '剧本转换' },
  { id: 'entity_extract', label: '实体提取' },
  { id: 'entity_consolidate', label: '实体跨集聚合' },
  { id: 'entity_setting', label: '实体设定生成' },
  { id: 'character_asset_prompt', label: '人物资产提示词' },
  { id: 'scene_asset_prompt', label: '场景资产提示词' },
  { id: 'prop_asset_prompt', label: '物品资产提示词' },
  { id: 'subject_match', label: '主体匹配' },
  { id: 'prompt_split', label: '提示词剧情切分' },
  { id: 'video_generate', label: '视频生成提示词' },
  { id: 'prompt_rerun', label: '提示词单卡重跑' },
  { id: 'video_agent', label: '视频生成助手' },
  { id: 'workflow_agent', label: '项目工作流 Agent' },
];

export const llmUseCases = [
  { id: 'split_planning', label: 'AI 切分建议 / 剧情时长切分' },
  { id: 'script_convert', label: '剧本转换' },
  { id: 'entity_extract', label: '实体提取' },
  { id: 'entity_consolidate', label: '实体跨集聚合' },
  { id: 'entity_setting', label: '实体设定生成' },
  { id: 'character_asset_prompt', label: '人物资产提示词' },
  { id: 'scene_asset_prompt', label: '场景资产提示词' },
  { id: 'prop_asset_prompt', label: '物品资产提示词' },
  { id: 'subject_match', label: '主体匹配' },
  { id: 'prompt_split', label: '提示词剧情切分' },
  { id: 'video_generate', label: '视频生成提示词' },
  { id: 'prompt_rerun', label: '提示词单卡重跑' },
  { id: 'video_agent', label: '视频生成助手 Agent' },
  { id: 'workflow_agent', label: '项目工作流 Agent' },
];
