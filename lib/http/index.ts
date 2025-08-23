// Export all utilities from params
export * from "./params";

// Specific named export for getLimitFromSearchParams
export { getLimitFromSearchParams } from "./params";

// Common HTTP utilities (add as needed)
export interface APIResponse<T = any> {
  data?: T;
  error?: string;
  message?: string;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
  page?: number;
}

export const DEFAULT_LIMIT = 25;
export const MAX_LIMIT = 100;
