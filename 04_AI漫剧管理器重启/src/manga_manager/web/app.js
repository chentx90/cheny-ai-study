const state = {
  works: [],
  activeWorkId: null,
  overview: null,
  tab: "episodes",
};

const $ = (selector) => document.querySelector(selector);

const entityLabels = {
  character: "人物",
  location: "场景",
  prop: "物品",
};

const assetLabels = {
  image: "图片",
  audio: "音频",
  video: "视频",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(path, { headers, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || {});
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(node._timer);
  node._timer = window.setTimeout(() => {
    node.hidden = true;
  }, 2800);
}

function currentWorkId() {
  return state.activeWorkId || state.works[0]?.id;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function applySavedLayout() {
  const sidebarWidth = Number(localStorage.getItem("manga.sidebarWidth") || 280);
  document.documentElement.style.setProperty("--sidebar-width", `${clamp(sidebarWidth, 220, 520)}px`);
  if (localStorage.getItem("manga.sidebarCollapsed") === "true") {
    document.body.classList.add("sidebar-collapsed");
  }
  updateSidebarToggleText();
}

function updateSidebarToggleText() {
  const button = $("#sidebar-toggle");
  if (!button) return;
  button.textContent = document.body.classList.contains("sidebar-collapsed") ? "展开侧栏" : "收起侧栏";
}

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  localStorage.setItem("manga.sidebarCollapsed", String(collapsed));
  updateSidebarToggleText();
}

function initResizablePanels() {
  const leftHandle = $("#left-resizer");

  const startDrag = (handle, side, event) => {
    if (side === "left" && document.body.classList.contains("sidebar-collapsed")) return;
    event.preventDefault();
    document.body.classList.add("resizing");
    handle.classList.add("active");

    const onMove = (moveEvent) => {
      const viewport = window.innerWidth;
      if (side === "left") {
        const width = clamp(moveEvent.clientX, 220, Math.min(520, viewport - 760));
        document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
        localStorage.setItem("manga.sidebarWidth", String(width));
      }
    };

    const stop = () => {
      document.body.classList.remove("resizing");
      handle.classList.remove("active");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", stop);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", stop);
  };

  leftHandle.addEventListener("mousedown", (event) => startDrag(leftHandle, "left", event));
  leftHandle.addEventListener("dblclick", () => {
    document.documentElement.style.setProperty("--sidebar-width", "280px");
    localStorage.setItem("manga.sidebarWidth", "280");
    setSidebarCollapsed(false);
  });
}

function panel(title, body, tools = "") {
  $("#panel").innerHTML = `
    <div class="panel-header">
      <h2>${escapeHtml(title)}</h2>
      <div class="toolbar">${tools}</div>
    </div>
    <div class="content">${body}</div>
  `;
}

function empty(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function closeModal() {
  const modal = $("#modal-root");
  modal.hidden = true;
  modal.innerHTML = "";
}

function configField(name, label, value, rows = 3) {
  return `
    <label class="config-field">
      <span>${escapeHtml(label)}</span>
      <textarea name="${escapeHtml(name)}" rows="${rows}">${escapeHtml(value)}</textarea>
    </label>
  `;
}

async function openPromptConfig() {
  if (!currentWorkId()) {
    toast("请先选择一个作品");
    return;
  }
  const { style_guide: style } = await api(`/api/works/${currentWorkId()}/prompt-config`);
  const modal = $("#modal-root");
  modal.hidden = false;
  modal.innerHTML = `
    <div class="modal-backdrop" data-close-modal></div>
    <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="prompt-config-title">
      <header class="modal-header">
        <div>
          <p class="eyebrow">PROMPT CONFIG</p>
          <h2 id="prompt-config-title">项目提示词配置</h2>
        </div>
        <button class="ghost-button" id="close-prompt-config" type="button">关闭</button>
      </header>
      <form id="prompt-config-form" class="config-form">
        ${configField("narrative_style", "叙事风格", style.narrative_style, 4)}
        ${configField("visual_style", "视觉风格", style.visual_style, 4)}
        ${configField("palette", "色彩与光影", style.palette, 3)}
        ${configField("render_keywords", "渲染关键词", style.render_keywords, 3)}
        ${configField("camera_language", "镜头语言", style.camera_language, 3)}
        ${configField("negative_prompt", "负面提示词", style.negative_prompt, 3)}
        <footer class="modal-actions">
          <button class="ghost-button" id="cancel-prompt-config" type="button">取消</button>
          <button type="submit">保存配置</button>
        </footer>
      </form>
    </section>
  `;
  modal.querySelectorAll("[data-close-modal], #close-prompt-config, #cancel-prompt-config").forEach((node) => {
    node.addEventListener("click", closeModal);
  });
  $("#prompt-config-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    await api(`/api/works/${currentWorkId()}/prompt-config`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    toast("提示词配置已保存");
    closeModal();
    await loadOverview();
    renderOverview();
  });
}

function renderWorks() {
  const list = $("#work-list");
  if (!state.works.length) {
    list.innerHTML = `<div class="empty">暂无作品</div>`;
    return;
  }
  list.innerHTML = state.works
    .map(
      (work) => `
        <button class="work-item ${work.id === currentWorkId() ? "active" : ""}" data-work="${escapeHtml(work.id)}" type="button">
          ${escapeHtml(work.title)}
          <span>${escapeHtml(work.id)} · ${escapeHtml(work.status)}</span>
        </button>
      `,
    )
    .join("");
  list.querySelectorAll("[data-work]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeWorkId = button.dataset.work;
      await api(`/api/works/${state.activeWorkId}/activate`, { method: "POST" });
      await loadOverview();
      renderWorks();
      renderOverview();
      await renderTab();
    });
  });
}

function renderOverview() {
  const title = $("#work-title");
  const overview = $("#overview");
  if (!state.overview) {
    title.textContent = "选择一个作品";
    overview.innerHTML = "";
    return;
  }
  const data = state.overview;
  title.textContent = data.work.title;
  const counts = data.counts;
  const stage = data.run_state?.stage || "M0";
  overview.innerHTML = [
    ["阶段", stage],
    ["剧集 / 场景", `${counts.episodes} / ${counts.scenes}`],
    ["镜头", counts.shots],
    ["实体", counts.entities],
    ["提示词", counts.video_prompts],
    ["成片", counts.generated_videos],
    ["素材", counts.assets],
    ["原文字数", data.source.chars],
  ]
    .map(([label, value]) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`)
    .join("");
}

async function renderEpisodes() {
  const { episodes } = await api(`/api/works/${currentWorkId()}/episodes`);
  const body = episodes.length
    ? `<div class="grid">${episodes
        .map(
          (episode) => `
            <details class="episode">
              <summary>第 ${episode.idx + 1} 集 · ${escapeHtml(episode.title)} · ${episode.scenes.length} 场</summary>
              <div class="scene-list">
                ${episode.scenes
                  .map(
                    (scene) => `
                      <article class="scene">
                        <div class="row-title">
                          <strong>第 ${scene.idx + 1} 个序列 · ${escapeHtml(scene.summary || scene.id)}</strong>
                          <span class="badge">${escapeHtml(scene.id)}</span>
                        </div>
                        <p class="muted">${escapeHtml(scene.time)} · ${escapeHtml(scene.location)} · ${escapeHtml(scene.pov)}</p>
                      </article>
                    `,
                  )
                  .join("")}
              </div>
            </details>
          `,
        )
        .join("")}</div>`
    : empty("还没有分集数据");
  panel("剧集与场景", body);
}

function entityCard(entity) {
  const variants = entity.variants.length
    ? entity.variants
        .slice(0, 5)
        .map((variant) => `${escapeHtml(variant.label)}：${escapeHtml(variant.appearance || variant.time_desc || "未填写")}`)
        .join("\n")
    : "暂无变体";
  return `
    <article class="entity">
      <div class="row-title">
        <strong>${escapeHtml(entity.name)}</strong>
        <span class="badge">${escapeHtml(entity.id)}</span>
      </div>
      <p class="muted">出现 ${entity.appearance_count} 场 · ${entity.aliases.map(escapeHtml).join(" / ")}</p>
      <div class="text">${variants}</div>
    </article>
  `;
}

async function renderEntities() {
  const { entities } = await api(`/api/works/${currentWorkId()}/entities`);
  const groups = {
    character: entities.filter((entity) => entity.type === "character"),
    location: entities.filter((entity) => entity.type === "location"),
    prop: entities.filter((entity) => entity.type === "prop"),
  };
  const body = entities.length
    ? `<div class="entity-sections">${Object.entries(groups)
        .map(
          ([kind, items]) => `
            <section class="entity-section">
              <div class="section-title">
                <h3>${entityLabels[kind]}</h3>
                <span class="badge">${items.length}</span>
              </div>
              <div class="entity-grid">
                ${items.length ? items.map(entityCard).join("") : empty(`暂无${entityLabels[kind]}`)}
              </div>
            </section>
          `,
        )
        .join("")}</div>`
    : empty("还没有实体设定");
  panel("设定实体", body);
}

function shotCard(shot, episodeIdx, sceneIdx) {
  return `
    <article class="shot">
      <div class="row-title">
        <strong>第 ${episodeIdx + 1} 集 / 第 ${sceneIdx + 1} 个序列 / 第 ${shot.idx + 1} 个镜头</strong>
        <span class="badge">${escapeHtml(shot.shot_type)}</span>
      </div>
      <p class="text">${escapeHtml(shot.action)}</p>
      <p class="muted">${escapeHtml(shot.emotion)} · ${shot.duration}s</p>
      ${shot.dialogue ? `<p class="text">“${escapeHtml(shot.dialogue)}”</p>` : ""}
    </article>
  `;
}

async function renderShots() {
  const { episodes } = await api(`/api/works/${currentWorkId()}/shot-tree`);
  const totalShots = episodes.reduce((sum, episode) => sum + episode.shot_count, 0);
  const body = totalShots
    ? `<div class="grid">${episodes
        .map(
          (episode) => `
            <details class="episode">
              <summary>第 ${episode.idx + 1} 集 · ${escapeHtml(episode.title)} · ${episode.shot_count} 镜头</summary>
              <div class="scene-list">
                ${episode.scenes
                  .map(
                    (scene) => `
                      <details class="scene-group">
                        <summary>第 ${scene.idx + 1} 个序列 · ${escapeHtml(scene.summary || scene.id)} · ${scene.shots.length} 镜头</summary>
                        <div class="shot-grid">
                          ${scene.shots.length
                            ? scene.shots.map((shot) => shotCard(shot, episode.idx, scene.idx)).join("")
                            : empty("这个场景还没有镜头")}
                        </div>
                      </details>
                    `,
                  )
                  .join("")}
              </div>
            </details>
          `,
        )
        .join("")}</div>`
    : empty("还没有镜头脚本");
  panel("镜头脚本", body);
}

async function renderPrompts() {
  const { prompts } = await api(`/api/works/${currentWorkId()}/prompts`);
  const body = prompts.length
    ? `<div class="prompt-grid">${prompts
        .map(
          (prompt) => `
            <article class="prompt">
              <div class="row-title">
                <strong>${escapeHtml(prompt.scene?.summary || prompt.scene_id)}</strong>
                <button class="ghost-button edit-prompt" data-scene="${escapeHtml(prompt.scene_id)}" type="button">编辑</button>
              </div>
              <p class="muted">${escapeHtml(prompt.scene_id)} · ${prompt.chars} 字</p>
              <p class="text">${escapeHtml(prompt.preview)}</p>
            </article>
          `,
        )
        .join("")}</div>`
    : empty("还没有视频提示词");
  panel("视频提示词", body);
  document.querySelectorAll(".edit-prompt").forEach((button) => {
    button.addEventListener("click", () => renderPromptEditor(button.dataset.scene));
  });
}

async function renderPromptEditor(sceneId) {
  const prompt = await api(`/api/works/${currentWorkId()}/prompts/${sceneId}`);
  panel(
    `编辑提示词 ${sceneId}`,
    `<div class="prompt-editor">
      <textarea id="prompt-text">${escapeHtml(prompt.text)}</textarea>
      <div class="toolbar">
        <button id="save-prompt" type="button">保存</button>
        <button id="back-prompts" class="ghost-button" type="button">返回</button>
      </div>
    </div>`,
  );
  $("#save-prompt").addEventListener("click", async () => {
    await api(`/api/works/${currentWorkId()}/prompts/${sceneId}`, {
      method: "PUT",
      body: JSON.stringify({ text: $("#prompt-text").value }),
    });
    toast("提示词已保存");
    await loadOverview();
    renderOverview();
  });
  $("#back-prompts").addEventListener("click", renderPrompts);
}

function mediaPreview(asset) {
  if (!asset.exists) return "";
  if (asset.kind === "image") {
    return `<img class="media" src="${asset.url}" alt="${escapeHtml(asset.filename)}" />`;
  }
  if (asset.kind === "audio") {
    return `<audio class="media" controls src="${asset.url}"></audio>`;
  }
  return `<video class="media" controls src="${asset.url}"></video>`;
}

function uploadOptions(entities) {
  return entities
    .map((entity) => {
      const variants = entity.variants.length ? entity.variants : [{ label: "" }];
      return variants
        .map(
          (variant) => `
            <option value="${escapeHtml(entity.id)}" data-variant="${escapeHtml(variant.label)}">
              ${escapeHtml(entityLabels[entity.type])} · ${escapeHtml(entity.name)}${variant.label ? ` · ${escapeHtml(variant.label)}` : ""}
            </option>
          `,
        )
        .join("");
    })
    .join("");
}

async function openAssetEditor(assetPath) {
  const [{ asset }, { entities }] = await Promise.all([
    api(`/api/works/${currentWorkId()}/assets/detail?path=${encodeURIComponent(assetPath)}`),
    api(`/api/works/${currentWorkId()}/entities`),
  ]);
  const modal = $("#modal-root");
  modal.hidden = false;
  modal.innerHTML = `
    <div class="modal-backdrop" data-close-modal></div>
    <section class="modal-card compact-modal" role="dialog" aria-modal="true" aria-labelledby="asset-editor-title">
      <header class="modal-header">
        <div>
          <p class="eyebrow">ASSET</p>
          <h2 id="asset-editor-title">编辑素材</h2>
        </div>
        <button class="ghost-button" id="close-asset-editor" type="button">关闭</button>
      </header>
      <form id="asset-editor-form" class="config-form">
        <div class="asset-editor-preview">
          ${mediaPreview(asset)}
          <p class="muted">${escapeHtml(asset.path)}</p>
        </div>
        <label class="config-field">
          <span>绑定实体 / 变体</span>
          <select name="target" id="asset-editor-target" required>
            ${uploadOptions(entities)}
          </select>
        </label>
        <label class="config-field">
          <span>素材类型</span>
          <select name="kind" id="asset-editor-kind">
            <option value="image">图片</option>
            <option value="audio">音频</option>
            <option value="video">视频</option>
          </select>
        </label>
        <footer class="modal-actions">
          <button class="ghost-button" id="cancel-asset-editor" type="button">取消</button>
          <button type="submit">保存素材</button>
        </footer>
      </form>
    </section>
  `;
  const target = $("#asset-editor-target");
  for (const option of target.options) {
    if (option.value === asset.entity_id && (option.dataset.variant || "") === asset.variant_label) {
      option.selected = true;
      break;
    }
  }
  $("#asset-editor-kind").value = asset.kind;
  modal.querySelectorAll("[data-close-modal], #close-asset-editor, #cancel-asset-editor").forEach((node) => {
    node.addEventListener("click", closeModal);
  });
  $("#asset-editor-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = target.options[target.selectedIndex];
    await api(`/api/works/${currentWorkId()}/assets?path=${encodeURIComponent(asset.path)}`, {
      method: "PATCH",
      body: JSON.stringify({
        entity_id: target.value,
        variant_label: selected.dataset.variant || "",
        kind: $("#asset-editor-kind").value,
      }),
    });
    toast("素材已更新");
    closeModal();
    await loadOverview();
    renderOverview();
    await renderAssets();
  });
}

async function renderAssets() {
  const [{ assets }, { entities }] = await Promise.all([
    api(`/api/works/${currentWorkId()}/assets`),
    api(`/api/works/${currentWorkId()}/entities`),
  ]);
  const uploader = `
    <form id="asset-upload-form" class="asset-uploader">
      <select id="asset-target" required>
        <option value="">选择实体/变体</option>
        ${uploadOptions(entities)}
      </select>
      <select id="asset-kind">
        <option value="image">图片</option>
        <option value="audio">音频</option>
        <option value="video">视频</option>
      </select>
      <input id="asset-file" type="file" required />
      <button type="submit">导入素材</button>
    </form>
  `;
  const cards = assets.length
    ? `<div class="asset-grid">${assets
        .map(
          (asset) => `
            <article class="asset">
              <div class="row-title">
                <strong>${escapeHtml(asset.entity_name)}</strong>
                <span class="badge">${assetLabels[asset.kind] || asset.kind}</span>
              </div>
              ${mediaPreview(asset)}
              <p class="muted">${escapeHtml(asset.variant_label)} · ${escapeHtml(asset.filename)}</p>
              <div class="asset-actions">
                <button class="ghost-button edit-asset" data-path="${escapeHtml(asset.path)}" type="button">编辑素材</button>
                <button class="ghost-button delete-asset" data-path="${escapeHtml(asset.path)}" type="button">删除素材</button>
              </div>
            </article>
          `,
        )
        .join("")}</div>`
    : empty("实体还没有绑定素材");
  panel("参考素材", `${uploader}${cards}`);
  bindAssetEvents();
}

function bindAssetEvents() {
  $("#asset-upload-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const target = $("#asset-target");
    const selected = target.options[target.selectedIndex];
    const file = $("#asset-file").files[0];
    if (!target.value || !file) return;
    const form = new FormData();
    form.append("entity_id", target.value);
    form.append("variant_label", selected.dataset.variant || "");
    form.append("kind", $("#asset-kind").value);
    form.append("file", file);
    await api(`/api/works/${currentWorkId()}/assets`, { method: "POST", body: form });
    toast("素材已导入");
    await loadOverview();
    renderOverview();
    await renderAssets();
  });
  document.querySelectorAll(".delete-asset").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.path;
      if (!window.confirm(`删除素材：${name}？`)) return;
      await api(`/api/works/${currentWorkId()}/assets?path=${encodeURIComponent(name)}`, { method: "DELETE" });
      toast("素材已删除");
      await loadOverview();
      renderOverview();
      await renderAssets();
    });
  });
  document.querySelectorAll(".edit-asset").forEach((button) => {
    button.addEventListener("click", () => {
      openAssetEditor(button.dataset.path).catch((error) => {
        console.error(error);
        toast(error.message);
      });
    });
  });
}

async function renderSource() {
  const source = await api(`/api/works/${currentWorkId()}/source`);
  panel(
    "原文",
    `<div class="source-editor">
      <textarea id="source-text">${escapeHtml(source.text)}</textarea>
      <div class="toolbar">
        <button id="save-source" type="button">保存原文</button>
        <span class="muted">${source.chars} 字</span>
      </div>
    </div>`,
  );
  $("#save-source").addEventListener("click", async () => {
    await api(`/api/works/${currentWorkId()}/source`, {
      method: "PUT",
      body: JSON.stringify({ text: $("#source-text").value }),
    });
    toast("原文已保存");
    await loadOverview();
    renderOverview();
  });
}

async function renderOperations() {
  const { operations } = await api(`/api/works/${currentWorkId()}/operations?limit=80`);
  const body = operations.length
    ? `<div class="operation-grid">${operations
        .map(
          (operation) => `
            <article class="operation">
              <div class="row-title">
                <strong>${escapeHtml(operation.command)}</strong>
                <span class="badge">${escapeHtml(operation.time)}</span>
              </div>
              <p class="text">${escapeHtml(operation.detail)}</p>
            </article>
          `,
        )
        .join("")}</div>`
    : empty("还没有操作记录");
  panel("操作日志", body);
}

async function renderTab() {
  if (!currentWorkId()) {
    panel("欢迎", empty("请先新建或选择一个作品"));
    return;
  }
  const map = {
    episodes: renderEpisodes,
    entities: renderEntities,
    shots: renderShots,
    prompts: renderPrompts,
    assets: renderAssets,
    source: renderSource,
    operations: renderOperations,
  };
  await map[state.tab]();
}

async function loadWorks() {
  const data = await api("/api/works");
  state.works = data.works;
  state.activeWorkId = data.active_work_id || state.activeWorkId || data.works[0]?.id || null;
}

async function loadOverview() {
  if (!currentWorkId()) {
    state.overview = null;
    return;
  }
  state.overview = await api(`/api/works/${currentWorkId()}/overview`);
}

function bindEvents() {
  $("#sidebar-toggle").addEventListener("click", () => {
    setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
  $("#prompt-config-button").addEventListener("click", () => {
    openPromptConfig().catch((error) => {
      console.error(error);
      toast(error.message);
    });
  });
  $("#refresh-button").addEventListener("click", async () => {
    await refresh();
    toast("已刷新");
  });
  $("#validate-button").addEventListener("click", async () => {
    if (!currentWorkId()) return;
    const report = await api(`/api/works/${currentWorkId()}/validate`, { method: "POST" });
    toast(report.ok ? "校验通过" : `发现 ${report.issues.length} 个问题`);
  });
  $("#create-work-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#new-work-title");
    const title = input.value.trim();
    if (!title) {
      toast("请输入作品标题");
      return;
    }
    try {
      const work = await api("/api/works", {
        method: "POST",
        body: JSON.stringify({ title }),
      });
      input.value = "";
      state.activeWorkId = work.id;
      await api(`/api/works/${work.id}/activate`, { method: "POST" });
      await refresh();
      toast("作品已创建");
    } catch (error) {
      toast(`新建失败：${error.message}`);
    }
  });
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", async () => {
      document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.tab = button.dataset.tab;
      await renderTab();
    });
  });
}

async function refresh() {
  await loadWorks();
  await loadOverview();
  renderWorks();
  renderOverview();
  await renderTab();
}

applySavedLayout();
initResizablePanels();
bindEvents();
refresh().catch((error) => {
  console.error(error);
  toast(error.message);
});
