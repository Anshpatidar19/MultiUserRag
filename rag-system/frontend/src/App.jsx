import { Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Chat from "./pages/Chat";
import KnowledgeBase from "./pages/KnowledgeBase";
import Upload from "./pages/Upload";
import Settings from "./pages/Settings";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />

      {/* Layout route: mounted once, keeps sidebar + session state stable
          while child pages swap via <Outlet/> inside ProtectedRoute. */}
      <Route element={<ProtectedRoute />}>
        <Route path="/chat" element={<Chat />} />
        <Route path="/knowledge-base" element={<KnowledgeBase />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/settings" element={<Settings />} />
      </Route>

      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}