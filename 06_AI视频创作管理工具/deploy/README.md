# fnOS / Docker 部署

## 首次部署

```bash
mkdir -p data/database data/projects data/config
docker compose build
docker compose up -d
```

浏览器访问 `http://<NAS-IP>:8010`（默认端口；可用 `AVM_HOST_PORT` 覆盖。前后端同端口，数据在 `./data`）。

## 同步更新

在项目根目录执行：

```bash
sh deploy/update.sh
```

或手动：

```bash
docker compose build
docker compose up -d
```

数据库、项目素材、加密密钥均在 `./data` 卷内，更新镜像不会丢失。

## 本机覆盖（可选）

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
```

用 override 配可选环境变量等；**不要把含个人 IP 的 override 提交进仓库**。结构说明见 [docs/00_项目结构.md](../docs/00_项目结构.md)。

### IPv6 公网访问 UI（可选）

星链云参考图已走 OSS，**不需要**把本机 IPv6 配成 `AVM_PUBLIC_BASE_URL`。IPv6 只用于你从外网打开管理页。

1. 路由器/光猫：确认已拿到公网 IPv6，防火墙放行 TCP `8010`（或你的 `AVM_HOST_PORT`）到 NAS。
2. NAS（fnOS）防火墙：同样放行该端口。
3. 若外网打不开而局域网 IPv4 正常，把 `docker-compose.yml` 里端口改成显式双栈（任选一种）：

```yaml
ports:
  - target: 8000
    published: ${AVM_HOST_PORT:-8010}
    protocol: tcp
    host_ip: "0.0.0.0"
  - target: 8000
    published: ${AVM_HOST_PORT:-8010}
    protocol: tcp
    host_ip: "::"
```

4. 访问：`http://[你的公网IPv6]:8010`（方括号不能省）。
5. 验证：`curl -6 -I "http://[你的IPv6]:8010/api/health"`

更新后执行 `docker compose up -d` 使端口生效。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `AVM_HOST_PORT` | `8010` | 宿主机映射端口 |
| `AVM_WORKSPACE_ROOT` | `/data` | 工作区根目录（容器内） |
| `AVM_DB_PATH` | `/data/database/app.db` | SQLite 路径 |
| `AVM_SERVE_UI` | `1` | 是否由后端托管前端静态资源 |
| `AVM_PUBLIC_BASE_URL` | 空 | 可选；星链云参考图优先走 OSS 直传 |

## 小云雀 CLI（可选）

容器内默认不含 `pippit-tool-cli`。可选方案：

1. 在 fnOS 宿主机安装 CLI，通过 compose 挂载二进制进容器；
2. 在设置页填写 `xyqCliPath` 指向挂载路径。

API Key / Access Key 仍通过应用设置页保存（加密写入 `data/config/local_secret.key`）。
