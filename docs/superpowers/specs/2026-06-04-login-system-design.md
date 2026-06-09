# 登录系统设计文档

> 日期: 2026-06-04 | 状态: 已确认 → 开发中

## 1. 需求概述

为文本标注系统添加用户登录功能，支持局域网团队协作场景。

## 2. 设计决策

| 维度 | 决定 |
|------|------|
| 使用场景 | 局域网团队协作 |
| 认证方式 | 用户名 + 密码 |
| 用户角色 | 所有人平等，无角色区分 |
| 视觉风格 | 极简白 — 大量留白，干净利落 |
| 页面布局 | 居中卡片式 |
| 登录/注册 | 同页切换（卡片内淡入淡出切换） |
| 卡片头部 | 图标(📝) + 标题 + 副标题 |
| 实现深度 | 标准方案：React Router + JWT + bcrypt |

## 3. 架构概览

```
浏览器
  /login → LoginPage (登录/注册卡片)
  /app   → AnnotatorApp (标注界面, RequireAuth 保护)
       │
       │ fetch + Authorization: Bearer <JWT>
       ▼
FastAPI (端口 8000)
  /api/auth/register  → 公开
  /api/auth/login     → 公开
  /api/auth/me        → 需认证
  /api/projects/*     → 需认证 (中间件)
       │
       ▼
SQLite: users 表 + 现有表
```

## 4. 后端设计

### 4.1 新增依赖
- `pyjwt>=2.8.0`
- `passlib[bcrypt]>=1.7.4`

### 4.2 数据库 — users 表
```python
class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, PK, autoincrement)
    username      = Column(String(64), unique, nullable, index)
    password_hash = Column(String(256), nullable)
    created_at    = Column(DateTime, server_default=func.now())
```

### 4.3 API 端点
| 方法 | 路径 | 认证 | 请求 | 响应 |
|------|------|------|------|------|
| POST | /api/auth/register | 无 | {username, password} | {token, user} |
| POST | /api/auth/login | 无 | {username, password} | {token, user} |
| GET | /api/auth/me | Bearer | — | {id, username} |

### 4.4 认证中间件
- 拦截所有 `/api/*` (排除 `/api/auth/*`)
- 校验 JWT，失败返回 401
- 成功则将 user_id 注入 `request.state`

### 4.5 JWT 配置
- 密钥: 随机生成，存 .env
- 过期: 7 天
- Payload: {user_id, username, exp}

## 5. 前端设计

### 5.1 新增依赖
- `react-router-dom` v6

### 5.2 文件结构
```
frontend/src/
├── main.tsx              # [改] BrowserRouter + AuthProvider
├── App.tsx               # [改] 路由出口
├── AnnotatorApp.tsx      # [新] 原 App.tsx 主内容
├── components/
│   └── LoginPage.tsx     # [新] 登录/注册卡片
├── contexts/
│   └── AuthContext.tsx    # [新] 认证状态管理
└── App.css               # [改] 增加登录页样式
```

### 5.3 路由
```
/login  → LoginPage (公开)
/app    → RequireAuth > AnnotatorApp (需登录)
*       → Navigate to /app
```

### 5.4 AuthContext
- 初始化时检查 localStorage token，调用 /api/auth/me 验证
- 提供: login(), register(), logout(), user, isAuthenticated

### 5.5 LoginPage 卡片设计
- 居中白色卡片 (340px 宽, border-radius 14px, 浅阴影)
- 顶部: 📝 图标 + "文本标注器" + "高效标注，精准分类"
- 登录模式: 用户名 + 密码 → 登录按钮 → "去注册"链接
- 注册模式: 用户名 + 密码 + 确认密码 → 注册按钮 → "去登录"链接
- 切换动画: 200ms 淡入淡出
- 错误提示: 表单上方浅红色提示条
- 加载态: 按钮显示"登录中..."并禁用

## 6. 改动清单

### 后端
- `requirements.txt` — 新增 pyjwt, passlib
- `server.py` — 注册认证路由 + 中间件
- `schema.py` — 新增 User 模型
- `services/auth_service.py` — 新增认证业务逻辑
- 新建 `.env` — JWT 密钥

### 前端
- `package.json` — 新增 react-router-dom
- `main.tsx` — 包裹 BrowserRouter + AuthProvider
- `App.tsx` — 改为路由出口
- `App.css` — 新增登录页样式
- `AnnotatorApp.tsx` — 新建，原 App 内容
- `LoginPage.tsx` — 新建，登录/注册卡片
- `AuthContext.tsx` — 新建，认证状态管理
