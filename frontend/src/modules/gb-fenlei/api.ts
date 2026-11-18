import type {
  ClassifyResponse,
  ExportResponse,
  HealthResponse,
  PendingAnalysis,
  ReferenceAnalysis,
} from "./types";

// 国标分类后端由 Vite 代理转发：/gb-api/api/* -> http://127.0.0.1:<GB_BACKEND_PORT>/api/*
const BASE = "/gb-api";

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

/** 把 FastAPI 常见错误体统一成一句中文提示。 */
function toApiError(payload: unknown, status: number): ApiError {
  if (payload && typeof payload === "object") {
    const body = payload as Record<string, unknown>;

    const error = body.error;
    if (error && typeof error === "object") {
      const detail = error as { code?: unknown; message?: unknown };
      const code = typeof detail.code === "string" ? detail.code : `HTTP_${status}`;
      const message =
        typeof detail.message === "string" ? detail.message : "请求失败，请稍后重试";
      return new ApiError(code, message);
    }

    if (typeof body.detail === "string") {
      return new ApiError(`HTTP_${status}`, body.detail);
    }

    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .map((item) => {
          if (item && typeof item === "object") {
            const msg = (item as { msg?: unknown }).msg;
            if (typeof msg === "string") return msg;
          }
          return "";
        })
        .filter(Boolean);
      if (messages.length) {
        return new ApiError(`HTTP_${status}`, messages.join("；"));
      }
    }

    if (typeof body.message === "string") {
      return new ApiError(`HTTP_${status}`, body.message);
    }
  }

  return new ApiError(`HTTP_${status}`, `请求失败（HTTP ${status}），请稍后重试`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError("NETWORK", "无法连接后端服务，请确认服务已启动后重试");
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : null;

  if (!response.ok) throw toApiError(payload, response.status);
  if (payload === null) {
    throw new ApiError(
      "INVALID_RESPONSE",
      "国标分类服务返回了非 JSON 响应，请确认后端已启动（默认端口 8000）",
    );
  }
  return payload as T;
}

function upload<T>(path: string, field: string, file: File): Promise<T> {
  const form = new FormData();
  form.append(field, file);
  return request<T>(path, { method: "POST", body: form });
}

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/api/health");
  },

  analyzeReference(file: File): Promise<ReferenceAnalysis> {
    return upload<ReferenceAnalysis>("/api/reference/analyze", "reference_file", file);
  },

  analyzePending(file: File): Promise<PendingAnalysis> {
    return upload<PendingAnalysis>("/api/pending/analyze", "pending_file", file);
  },

  classifyTask(
    referenceId: string,
    pendingId: string,
    threshold: number,
  ): Promise<ClassifyResponse> {
    return request<ClassifyResponse>("/api/tasks/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reference_id: referenceId,
        pending_id: pendingId,
        threshold,
      }),
    });
  },

  exportTask(
    taskId: string,
    overrides: Record<string, string>,
  ): Promise<ExportResponse> {
    return request<ExportResponse>("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, overrides }),
    });
  },
};

/** 后端可能返回相对下载地址，这里补上 API 基地址。 */
export function resolveDownloadUrl(url: string): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  const path = url.startsWith("/") ? url : `/${url}`;
  return `${BASE}${path}`;
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
