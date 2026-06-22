# AI 打包规范 —— 客户专用

> 约束对象：AI（Claude Code / 其他 AI 编程助手）
> 每一次为这个客户打包时，必须严格遵守以下规则，逐条自检，禁止凭经验跳过。

---

## 一、客户环境（已确认，不可变更）

| 项目 | 值 | 含义 |
|------|-----|------|
| 操作系统 | RHEL 7.6 (Maipo) | 默认 SELinux Enforcing、firewalld |
| 架构 | x86_64 | 镜像必须用 linux/amd64 平台 |
| Docker | 20.10.9 | 支持多阶段构建、`COPY --from` |
| docker-compose | **1.17.1**（2017 年 Python 版） | 仅支持 Compose file format ≤ 3.5 |
| `docker compose` 命令 | **不存在** | 所有命令必须用 `docker-compose`（有连字符） |
| 网络 | **离线**（无互联网） | 不能拉取基础镜像，必须交付完整 tar |
| 可用端口 | **仅 3001** | 全链路统一 3001，容器内外都用 3001(除非客户明确要求换端口号,例如3002) |
| 部署方式 | zip + tar，解压后 `docker load` + `docker-compose -f docker-compose.offline.yml up -d` |

---

## 二、docker-compose.offline.yml 固定模板

以下配置为最终确定版，客户以后明确要求换端口号，则把 `3001` 全局替换，volumes根据实际情况调整：

```yaml
version: "3.3"
services:
  ontology-tool:
    image: multi-view-ontology-tool:latest
    container_name: multi-view-ontology-tool
    ports:
      - "3001:3001"
    volumes:
      - ./backend/projects:/app/backend/projects:z
      - ./backend/uploads:/app/backend/uploads:z
      - ./backend/users.xlsx:/app/backend/users.xlsx:z
    restart: unless-stopped
    security_opt:
      - seccomp:unconfined
    ulimits:
      nproc: 65535
      nofile:
        soft: 65535
        hard: 65535
    environment:
      - OPENBLAS_NUM_THREADS=1
      - GOTO_NUM_THREADS=1
      - OMP_NUM_THREADS=1
```

### 每一项的原因

| 配置项 | 不加的后果 |
|--------|-----------|
| `version: "3.3"`（必须带次版本号+双引号） | docker-compose 1.17.1 不识别 → 回退 v1 schema → `unsupported config option` |
| `security_opt: seccomp:unconfined` | seccomp 阻止 onnxruntime 创建线程 → 容器启动后服务崩溃 |
| `ulimits: nproc/nofile 65535` | 容器线程数/文件数不足 → OpenBLAS 初始化失败 |
| `environment: OPENBLAS/GOTO/OMP_NUM_THREADS=1` | OpenBLAS 多线程触发 rlimit 校验 → 启动失败 |
| volumes `:z` 标签 | RHEL 7 SELinux 阻止容器读写挂载目录 → 数据无法加载 |
| `restart: unless-stopped` | 容器意外退出不会自动恢复 |

---

## 三、Dockerfile 固定规则

```dockerfile
EXPOSE 3001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]
```

**规则**：端口号与 compose 一致（当前均为 3001）。若客户将来换端口，Dockerfile + compose + vite.config.js + main.py 的 `__main__` 四处必须**同步替换**。

---

## 四、前端代码禁令（历史 bug 高发区，不一定适配所有情况，但需要检查）

### 4.1 绝对禁止硬编码端口和 IP

```js
// ❌ 以下写法都是 bug，曾在客户环境实际触发过错误：
const API_BASE = `http://${window.location.hostname}:8000`;
const API_BASE = `http://${window.location.hostname}:3001`;
const API_BASE = "http://127.0.0.1:8000";
const API_BASE = "http://localhost:8000";
const API_BASE = (typeof window !== "undefined" ? `http://${window.location.hostname}:8000` : "http://127.0.0.1:8000");

// ✅ 全项目统一使用：
const API_BASE = import.meta.env.VITE_API_BASE || "";
```

**空字符串 = 相对路径**。浏览器访问 `http://IP:3001`，请求自动发到 `http://IP:3001/api/xxx`，端口自适应。

**打包前必须执行**：全局搜索 `8000`、`3001`、`localhost`、`127.0.0.1`、`hostname`，确认没有出现在任何前端 `.vue` / `.js` 文件的 API_BASE 赋值中。唯一允许出现的是 `vite.config.js` 的 dev proxy（开发环境专用，不影响 Docker）。

### 4.2 所有 API 调用前必须有参数空值守卫

```js
// ❌ projectId 为 null 时会拼出 /api/xxx/null → 404
async function loadData() {
  const resp = await fetch(`${API_BASE}/api/xxx/${props.projectId}`);
}

// ✅ 必须加守卫
async function loadData() {
  if (!props.projectId || props.projectId === 'null') return;
  const resp = await fetch(`${API_BASE}/api/xxx/${props.projectId}`);
}
```

### 4.3 模板必须守卫依赖数据的组件

```html
<!-- ❌ currentProjectId 为 null 时组件仍渲染，内部 onMounted 触发无效请求 -->
<DataView :projectId="currentProjectId" />

<!-- ✅ -->
<DataView v-if="currentProjectId" :projectId="currentProjectId" />
```

### 4.4 登录成功后必须重新加载数据

```js
function onLoginSuccess(user) {
  currentUser.value = user;
  isLoggedIn.value = true;
  localStorage.setItem("token", JSON.stringify(user));
  loadProjects();  // ← 必须！onMounted 中的 loadProjects 可能已失败
}
```

### 4.5 禁止空 catch 吞错

```js
// ❌ 错误被静默吞掉，用户不知道出了什么错
try { await request("/api/xxx"); } catch (e) {}

// ✅ 至少给出提示
try { await request("/api/xxx"); } catch (error) {
  statusMessage.value = `操作失败：${error.message}`;
}
```

---

## 五、后端代码规则（历史 bug 高发区，不一定适配所有情况，但需要检查）

### 5.1 路由必须成对

前端 `GET` + `PUT` 同一个 URL 时，后端两个方法都要实现：

```python
# ✅ 正确
@app.get("/api/weights/{id}")
def get_weights(id: str): ...

@app.put("/api/weights/{id}")
def update_weights(id: str, payload: ...): ...

# ❌ 只有 PUT 没有 GET → 前端初始化时 404（历史上真实发生过）
```

### 5.2 数据写入必须捕获磁盘异常

```python
def _save_data(path, data):
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, IOError) as e:
        print(f"[ERROR] 保存失败: {e}", file=sys.stderr)
```

### 5.3 数据加载必须防崩溃

```python
def _load_index():
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []   # 文件不存在或损坏时返回空，不崩溃
```

### 5.4 favicon 必须返回 200

浏览器会自动请求 `/favicon.ico`。后端必须有路由处理：

```python
@app.get("/favicon.ico")
async def favicon():
    return Response(content=..., media_type="image/x-icon")
```

---

## 六、打包文件规范（历史 bug 高发区，不一定适配所有情况，但需要检查）

### 6.1 .gitattributes

```
*.yml text eol=lf
*.yaml text eol=lf
Dockerfile text eol=lf
.dockerignore text eol=lf
```

**原因**：Windows 打包成 zip 时，若无此文件，YAML/Dockerfile 会被转为 CRLF。客户 Linux 解压后可能被旧版 PyYAML 误解析。

### 6.2 .gitignore —— 默认项目数据必须追踪

```gitignore
# ❌ 如果以下两行都存在，项目数据不会进入 zip，客户拿到空系统
backend/projects/*.json
backend/projects/index.json

# ✅ 白名单保留 demo 项目
backend/projects/*.json
!backend/projects/<demo-project-id>.json
!backend/projects/index.json
```

### 6.3 .dockerignore —— 排除运行时数据

```
backend/projects/*.json    # volume 挂载提供，不打入镜像
backend/uploads
```

### 6.4 交付文件

| 文件 | 说明 |
|------|------|
| `multi-view-ontology-tool.tar` | `docker save` 导出的完整镜像 |
| `docker-compose.offline.yml` | 离线部署配置（随项目 zip 一起给） |
| `部署说明.txt` | 客户操作步骤 |

---

## 七、AI 打包前自检清单（每次打包必须逐条确认，历史 bug 高发区，不一定适配所有情况，但需要检查）

```
□ 1. 前端全局搜索 :8000 :3001 localhost 127.0.0.1 hostname → 确认只有 vite.config.js 有（dev proxy，合法）
□ 2. 前端全局搜索 catch (e) {} → 确认无空异常处理
□ 3. 前端所有 fetch/request 调用 → 确认传入参数有 null/undefined 守卫
□ 4. 后端路由列表导出 → 逐一对照前端请求列表，确认无缺失方法
□ 5. docker-compose.offline.yml → version: "3.3" / 端口 3001:3001 / :z 标签 / seccomp / ulimits / environment
□ 6. Dockerfile → EXPOSE 3001 / CMD --port 3001
□ 7. vite.config.js → proxy target http://127.0.0.1:3001
□ 8. .gitignore → demo 项目 JSON 在 git 追踪中
□ 9. .dockerignore → 排除了 backend/projects/*.json
□ 10. 容器启动后 curl 验证：
     - /api/projects → 200, 返回默认项目
     - /api/perspective/{demo-id}/leader → 200
     - / → 200
     - /favicon.ico → 200 (非 404)
```
