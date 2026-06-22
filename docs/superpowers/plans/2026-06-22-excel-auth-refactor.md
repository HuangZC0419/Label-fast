# Excel Auth Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace database-backed user registration/login with `backend/users.xlsx` as the only credential source, keep JWT-based session auth, remove registration, and delete obsolete helper entrypoints.

**Architecture:** The backend continues to issue and validate JWTs, but user identity comes from an in-memory cache loaded from `users.xlsx` at process startup. `server.py` keeps being the single backend entrypoint, while the frontend login flow is simplified to login-only and `/api/auth/me` resolves the current user from JWT payload instead of the SQLite `users` table.

**Tech Stack:** FastAPI, PyJWT, openpyxl, React, TypeScript

---

### Task 1: Replace DB User Lookup With Excel Credential Store

**Files:**
- Modify: `backend/文本标注器/services/auth_service.py`
- Input: `backend/users.xlsx`

- [ ] **Step 1: Add a lightweight Excel user model and workbook loader**

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


@dataclass(frozen=True)
class ExcelUser:
    id: int
    username: str
    password: str
    role: str = ""
    name: str = ""


USERS_XLSX_PATH = Path(__file__).resolve().parents[2] / "users.xlsx"
EXCEL_USERS_BY_USERNAME: dict[str, ExcelUser] = {}
```

- [ ] **Step 2: Implement the loader that reads the first worksheet by header name**

```python
def _normalize_cell(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def load_excel_users() -> dict[str, ExcelUser]:
    if not USERS_XLSX_PATH.exists():
        raise RuntimeError(f"用户账号文件不存在: {USERS_XLSX_PATH}")

    workbook = load_workbook(USERS_XLSX_PATH, read_only=True, data_only=True)
    worksheet = workbook[workbook.sheetnames[0]]
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        raise RuntimeError("users.xlsx 为空")

    header = [_normalize_cell(cell).lower() for cell in rows[0]]
    required = {"username", "password"}
    if not required.issubset(set(header)):
        raise RuntimeError("users.xlsx 缺少 username/password 表头")

    username_index = header.index("username")
    password_index = header.index("password")
    role_index = header.index("role") if "role" in header else None
    name_index = header.index("name") if "name" in header else None

    users: dict[str, ExcelUser] = {}
    next_id = 1
    for row in rows[1:]:
        if row is None:
            continue
        username = _normalize_cell(row[username_index] if username_index < len(row) else None)
        password = _normalize_cell(row[password_index] if password_index < len(row) else None)
        if not username or not password:
            continue
        users[username] = ExcelUser(
            id=next_id,
            username=username,
            password=password,
            role=_normalize_cell(row[role_index] if role_index is not None and role_index < len(row) else None),
            name=_normalize_cell(row[name_index] if name_index is not None and name_index < len(row) else None),
        )
        next_id += 1

    if not users:
        raise RuntimeError("users.xlsx 中没有可用账号")
    return users
```

- [ ] **Step 3: Load the workbook at import/startup and expose lookup helpers**

```python
EXCEL_USERS_BY_USERNAME = load_excel_users()


def get_user_by_username(username: str) -> ExcelUser | None:
    return EXCEL_USERS_BY_USERNAME.get(username)


def get_user_by_id(user_id: int) -> ExcelUser | None:
    for user in EXCEL_USERS_BY_USERNAME.values():
        if user.id == user_id:
            return user
    return None
```

- [ ] **Step 4: Replace `login_user()` so it validates plain-text Excel credentials**

```python
def login_user(username: str, password: str) -> dict:
    user = get_user_by_username(username)
    if not user or user.password != password:
        raise ValueError("用户名或密码错误")

    token = create_token(user.id, user.username)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "name": user.name or user.username,
        },
    }
```

- [ ] **Step 5: Remove dead DB-auth code**

```python
# delete:
# - import bcrypt
# - get_session / User imports
# - hash_password()
# - verify_password()
# - register_user()
```

- [ ] **Step 6: Run a backend smoke check for workbook loading**

Run:

```bash
cd h:\Git\Label-fast-main\backend
python -c "from 文本标注器.services.auth_service import EXCEL_USERS_BY_USERNAME; print(sorted(EXCEL_USERS_BY_USERNAME))"
```

Expected:

```text
['user', '用户']
```

- [ ] **Step 7: Commit**

```bash
git add backend/文本标注器/services/auth_service.py
git commit -m "refactor: load auth users from excel"
```

### Task 2: Simplify FastAPI Auth Routes Around JWT + Excel Users

**Files:**
- Modify: `backend/server.py`

- [ ] **Step 1: Remove the registration route**

```python
# delete the entire /api/auth/register handler from server.py
```

- [ ] **Step 2: Update `/api/auth/me` to resolve the current user from Excel-backed auth service**

```python
@app.get("/api/auth/me")
def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header[len("Bearer "):]
    payload = auth_service.verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="令牌无效")

    user = auth_service.get_user_by_id(int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "name": user.name or user.username,
    }
```

- [ ] **Step 3: Keep the login route shape unchanged so the frontend token flow keeps working**

```python
@app.post("/api/auth/login")
def login_api(data: Dict[str, Any] = Body(...)):
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    try:
        return auth_service.login_user(username, password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
```

- [ ] **Step 4: Verify login and `me` end-to-end**

Run:

```bash
cd h:\Git\Label-fast-main\backend
python -c "import requests; s=requests.Session(); r=s.post('http://127.0.0.1:8000/api/auth/login', json={'username':'user','password':'123456'}); print(r.status_code); data=r.json(); print(sorted(data['user'].keys())); r2=s.get('http://127.0.0.1:8000/api/auth/me', headers={'Authorization': f'Bearer {data[\"token\"]}'}); print(r2.status_code); print(r2.json()['username'])"
```

Expected:

```text
200
['id', 'name', 'role', 'username']
200
user
```

- [ ] **Step 5: Commit**

```bash
git add backend/server.py
git commit -m "refactor: switch auth endpoints to excel users"
```

### Task 3: Remove Registration From Frontend Login Flow

**Files:**
- Modify: `frontend/src/contexts/AuthContext.tsx`
- Modify: `frontend/src/components/LoginPage.tsx`

- [ ] **Step 1: Remove `register` from the auth context contract**

```tsx
interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}
```

- [ ] **Step 2: Delete the `/api/auth/register` fetch implementation**

```tsx
// remove the entire register() function and stop exposing it in AuthContext.Provider
```

- [ ] **Step 3: Convert `LoginPage` to login-only UI**

```tsx
const { login } = useAuth()
// remove:
// - isRegister state
// - confirmPassword state
// - switchMode()
// - register branch inside handleSubmit()
// - bottom "立即注册" toggle area
```

- [ ] **Step 4: Replace the dev hint so it reflects Excel-managed accounts**

```tsx
<div style={{ ... }}>
  <strong>账号由管理员维护</strong><br />
  请使用 `backend/users.xlsx` 中配置的用户名和密码登录
</div>
```

- [ ] **Step 5: Run a frontend build check**

Run:

```bash
cd h:\Git\Label-fast-main\frontend
npm run build
```

Expected:

```text
vite v...
✓ built in ...
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/contexts/AuthContext.tsx frontend/src/components/LoginPage.tsx
git commit -m "refactor: remove self-service registration"
```

### Task 4: Delete Obsolete Entry Scripts And Update Usage Notes

**Files:**
- Delete: `backend/seed_dev_user.py`
- Delete: `backend/serve_static.py`
- Modify: `README.md`

- [ ] **Step 1: Delete obsolete scripts**

```text
Delete backend/seed_dev_user.py
Delete backend/serve_static.py
```

- [ ] **Step 2: Update README startup and account instructions**

```md
## 启动后端

```bash
cd h:\Git\Label-fast-main\backend
python -m pip install -r requirements.txt
python server.py
```

## 账号管理

- 管理员维护 `backend/users.xlsx`
- 修改表格后重启后端生效
- 系统不提供自助注册功能
```

- [ ] **Step 3: Verify the final app contract**

Run:

```bash
cd h:\Git\Label-fast-main\backend
python server.py
```

Then verify:

```text
1. GET /api/health returns {"status":"ok"}
2. POST /api/auth/login with users.xlsx credentials returns 200
3. GET / serves built frontend if frontend/dist exists
4. POST /api/auth/register returns 404 or no longer exists
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git rm backend/seed_dev_user.py backend/serve_static.py
git commit -m "chore: remove obsolete auth helper scripts"
```
