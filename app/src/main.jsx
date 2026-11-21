import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { useRoute } from "./lib/router";
import Shell from "./components/Shell";
import { WorkOrderProvider } from "./components/WorkOrderPanel";
import Overview from "./pages/Overview";
import Wards from "./pages/Wards";
import Flags from "./pages/Flags";
import Contractors from "./pages/Contractors";
import Plan from "./pages/Plan";
import Track from "./pages/Track";

const PAGES = { overview: Overview, wards: Wards, flags: Flags, contractors: Contractors, plan: Plan, track: Track };
const TITLES = { overview: "Overview", wards: "Ward money trail", flags: "Audit flags", contractors: "Contractors", plan: "Next rupee", track: "Complaint tracker" };

function App() {
  const route = useRoute();
  const Page = PAGES[route.page] || Overview;
  useEffect(() => {
    document.title = `${TITLES[route.page] || "Overview"} | Follow the Rupee`;
    window.scrollTo(0, 0); // only on page change, so selecting a ward or contractor in place keeps the scroll position
  }, [route.page]);
  return (
    <WorkOrderProvider>
      <Shell page={PAGES[route.page] ? route.page : "overview"}>
        <Page key={route.page} id={route.id} query={route.query} />
      </Shell>
    </WorkOrderProvider>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
