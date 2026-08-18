import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import StatusBar from "./components/StatusBar";
import Dashboard from "./pages/Dashboard";
import Activity from "./pages/Activity";
import Configure from "./pages/Configure";
import Research from "./pages/Research";
import Reports from "./pages/Reports";
import Updates from "./pages/Updates";
import Vendors from "./pages/Vendors";
import VendorProfile from "./pages/VendorProfile";
import Desks from "./pages/Desks";

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/configure" element={<Configure />} />
          <Route path="/research" element={<Research />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/updates" element={<Updates />} />
          <Route path="/vendors" element={<Vendors />} />
          <Route path="/vendors/:vendorName" element={<VendorProfile />} />
          <Route path="/desks" element={<Desks />} />
        </Routes>
      </main>
      <StatusBar />
    </div>
  );
}
