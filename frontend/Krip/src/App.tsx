import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate,} from "react-router-dom";
import AppShell from "./components/AppShell";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import HomePage from "./pages/HomePage";
import MenuPage from "./pages/MenuPage";
import MatePage from "./pages/MatePage";
import ChatPage from "./pages/ChatPage";
import MyPage from "./pages/MyPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import PlanSelectionPage from "./pages/PlanSelectionPage";
import AiPlanDesignPage from "./pages/AiPlanDesignPage";
import AiPlanResultPage from "./pages/AiPlanResultPage";
import ManualPlanPage from "./pages/Manualplanpage";
import {
  clearPreferences,
  clonePreferences,
  defaultPreferences,
  getSavedPlanById,
  loadPreferences,
  savePreferences,
  type AiPreferenceState,
} from "./team/api/aiPlanShared";

function AiPlanDesignRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const planId = new URLSearchParams(location.search).get("planId");
  const [preferences, setPreferences] = useState<AiPreferenceState>(() => {
    const savedPlan = getSavedPlanById(planId);
    if (savedPlan?.type === "ai" && savedPlan.aiPreferences) {
      return clonePreferences(savedPlan.aiPreferences);
    }
    return clonePreferences(defaultPreferences);
  });
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    if (!planId) {
      clearPreferences();
    }
  }, [planId]);

  useEffect(() => {
    savePreferences(preferences);
  }, [preferences]);

  const handleSubmit = async () => {
    setIsGenerating(true);
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    savePreferences(preferences);
    setIsGenerating(false);
    navigate("/plan/ai/result");
  };

  return (
    <AiPlanDesignPage
      value={preferences}
      onBack={() => navigate("/plan")}
      onChange={setPreferences}
      onSubmit={() => void handleSubmit()}
      isGenerating={isGenerating}
    />
  );
}

function AiPlanResultRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const planId = new URLSearchParams(location.search).get("planId");
  const preferences = useMemo(() => {
    const savedPlan = getSavedPlanById(planId);
    if (savedPlan?.type === "ai" && savedPlan.aiPreferences) {
      return clonePreferences(savedPlan.aiPreferences);
    }
    return clonePreferences(loadPreferences());
  }, [planId]);

  return (
    <AiPlanResultPage
      preferences={preferences}
      onBack={() => navigate("/plan")}
      onEdit={() =>
        navigate(planId ? `/plan/ai?planId=${planId}` : "/plan/ai")
      }
    />
  );
}

function ManualPlanRoute() {
  const navigate = useNavigate();
  return <ManualPlanPage onBack={() => navigate("/plan")} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<AppShell />}>
          <Route path="/home" element={<HomePage />} />
          <Route path="/plan" element={<PlanSelectionPage />} />
          <Route path="/plan/ai" element={<AiPlanDesignRoute />} />
          <Route path="/plan/ai/result" element={<AiPlanResultRoute />} />
          <Route path="/plan/manual" element={<ManualPlanRoute />} />
          <Route path="/menu" element={<MenuPage />} />
          <Route path="/mate" element={<MatePage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/my" element={<MyPage />} />
        </Route>
        <Route path="/chat/:id" element={<PlaceholderPage />} />
        <Route path="/spots/:id" element={<PlaceholderPage />} />
        <Route path="/profile/:id" element={<PlaceholderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
