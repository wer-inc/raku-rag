import FullSaasScreen from "../components/FullSaasScreen";
import { loadStandaloneScreen } from "../../lib/standalone-screen";

export default function OperationsPage() {
  const screen = loadStandaloneScreen("/operations");
  if (!screen) {
    throw new Error("standalone screen for /operations is missing");
  }
  return <FullSaasScreen pathname="/operations" screen={screen} />;
}
