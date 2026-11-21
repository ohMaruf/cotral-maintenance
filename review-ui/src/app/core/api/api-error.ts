import { HttpErrorResponse } from '@angular/common/http';

export type ApiErrorKind = 'not_found' | 'conflict' | 'invalid' | 'server' | 'network';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function detailMessage(body: unknown): string | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (typeof d === 'object' && d !== null && 'msg' in d ? String(d.msg) : null))
      .filter((m): m is string => m !== null);
    return msgs.length ? msgs.join('; ') : null;
  }
  return null;
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (!(err instanceof HttpErrorResponse)) {
    return new ApiError('network', 0, err instanceof Error ? err.message : 'Unexpected error');
  }
  const detail = detailMessage(err.error);
  switch (true) {
    case err.status === 0:
      return new ApiError('network', 0, 'Cannot reach the review server. Is it running?');
    case err.status === 404:
      return new ApiError('not_found', 404, detail ?? 'Not found');
    case err.status === 409:
      return new ApiError('conflict', 409, detail ?? 'Already judged');
    case err.status >= 400 && err.status < 500:
      return new ApiError('invalid', err.status, detail ?? 'The request was rejected');
    default:
      return new ApiError('server', err.status, detail ?? 'The review server failed');
  }
}
