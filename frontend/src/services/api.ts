export type SourceChunk = {
  source: string;
  chunk_id: number;
  score: number;
  preview: string;
};

export type ChatResponse = {
  answer: string;
  sources: SourceChunk[];
};

export type SkippedFile = {
  filename: string;
  reason: string;
};

export type UploadResponse = {
  uploaded: string[];
  skipped: SkippedFile[];
  indexed_chunks: number;
  documents: string[];
};

export type DocumentListResponse = {
  documents: string[];
  indexed_chunks: number;
};

export type HealthResponse = {
  status: string;
  embedder_ready: boolean;
  llm_configured: boolean;
  indexed_chunks: number;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceChunk[];
};

export type UploadStatusKind = 'idle' | 'uploading' | 'success' | 'error';

export class ApiError extends Error {
  status: number;
  extra: { skipped?: SkippedFile[]; message?: string } | null;

  constructor(
    message: string,
    status: number,
    extra: { skipped?: SkippedFile[]; message?: string } | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.extra = extra;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

async function readError(response: Response) {
  try {
    const data = await response.json();
    const detail = data.detail;
    if (typeof detail === 'string') {
      return { message: detail, extra: null };
    }
    if (detail && typeof detail === 'object') {
      return {
        message: detail.message || 'Request failed.',
        extra: detail,
      };
    }
    return { message: data.message || `Request failed (${response.status})`, extra: data };
  } catch {
    return { message: `Request failed (${response.status} ${response.statusText})`, extra: null };
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const error = await readError(response);
    throw new ApiError(error.message, response.status, error.extra);
  }
  return response.json() as Promise<T>;
}

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const file of files) {
    const relative = file.webkitRelativePath || file.name;
    form.append('files', file, relative);
  }
  return request<UploadResponse>('/api/documents/upload', {
    method: 'POST',
    body: form,
  });
}

export function sendChat(message: string) {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
}

export function listDocuments() {
  return request<DocumentListResponse>('/api/documents');
}

export function deleteDocument(name: string) {
  return request<DocumentListResponse>(`/api/documents?name=${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export function getHealth() {
  return request<HealthResponse>('/api/health');
}
