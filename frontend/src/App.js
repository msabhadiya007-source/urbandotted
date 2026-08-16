import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Loading } from "@/components/ui-kit";
import Login from "@/pages/Login";
import Overview from "@/pages/Overview";
import WarRoom from "@/pages/WarRoom";
import Opportunities from "@/pages/Opportunities";
import Keywords from "@/pages/Keywords";
import Technical from "@/pages/Technical";
import Cost from "@/pages/Cost";
import AIOperations from "@/pages/AIOperations";
import Connections from "@/pages/Connections";

const Protected = ({ children }) => {
  const { user } = useAuth();
  if (user === null) return <Loading label="Restoring session" />;
  if (user === false) return <Navigate to="/login" replace />;
  return children;
};

const AnonymousOnly = ({ children }) => {
  const { user } = useAuth();
  if (user === null) return <Loading label="Restoring session" />;
  if (user) return <Navigate to="/" replace />;
  return children;
};

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <Toaster theme="dark" position="bottom-right" />
          <Routes>
            <Route path="/login" element={<AnonymousOnly><Login /></AnonymousOnly>} />
            <Route element={<Protected><Layout /></Protected>}>
              <Route path="/" element={<Overview />} />
              <Route path="/war-room/:market" element={<WarRoom />} />
              <Route path="/opportunities" element={<Opportunities />} />
              <Route path="/keywords" element={<Keywords />} />
              <Route path="/technical" element={<Technical />} />
              <Route path="/cost" element={<Cost />} />
              <Route path="/ai-operations" element={<AIOperations />} />
              <Route path="/connections" element={<Connections />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
