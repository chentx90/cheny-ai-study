# Docker 运行

## 构建并启动

```bash
docker compose up --build
```

启动后访问：

```text
http://127.0.0.1:8010
```

## 数据挂载

`docker-compose.yml` 会把本机 `./data` 挂载到容器 `/app/data`，因此作品、素材、提示词和生成视频仍然保存在项目目录里。

`config.toml` 以只读方式挂载到容器内，用于读取 LLM 和项目默认配置。

## CLI

进入容器后可以执行项目 CLI：

```bash
docker compose exec manga-manager manga list
docker compose exec manga-manager manga info
```

Web 右侧的 AI 工具面板也可以执行受限 CLI，允许：

- `manga ...`
- `python -m manga_manager.cli ...`

为了避免把 Web 变成不受限终端，其他命令会被后端拒绝。
