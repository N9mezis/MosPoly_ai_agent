import { Navigate, useLocation } from "react-router-dom";
import { ApiError } from "./api/client";
import { describeProblem } from "./problems";

export function ErrorMessage({ error, context }: { error: Error | null; context?: "login" }) {
  const location = useLocation();
  if (!error) return null;
  if (error instanceof ApiError && error.status === 401 && context !== "login") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  const problem = describeProblem(error, context);
  return <div role="alert" className="error"><strong>{problem.title}</strong><p>{problem.hint}</p></div>;
}
