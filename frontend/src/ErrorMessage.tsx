import { Navigate } from "react-router-dom";
import { ApiError } from "./api/client";

export function ErrorMessage({ error }: { error: Error | null }) {
  if (error instanceof ApiError && error.status === 401) return <Navigate to="/login" replace />;
  return error && <p role="alert" className="error">{error.message}</p>;
}
