import { Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Chat from "./pages/Chat";
import Documents from "./pages/Documents";
import Settings from "./pages/Settings";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />

      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <Chat />
          </ProtectedRoute>
        }
      />
      <Route
        path="/documents"
        element={
          <ProtectedRoute>
            <Documents />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload"
        element={
          <ProtectedRoute>
            <Documents />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <Settings />
          </ProtectedRoute>
        }
      />

      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
