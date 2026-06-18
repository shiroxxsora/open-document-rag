import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) {
    return <main className="shell"><p>Loading...</p></main>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
