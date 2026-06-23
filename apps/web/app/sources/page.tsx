import FullSaasScreen from "../components/FullSaasScreen";
import { loadStandaloneScreen } from "../../lib/standalone-screen";

export default function SourcesPage() {
  const screen = loadStandaloneScreen("/sources");
  if (!screen) {
    throw new Error("standalone screen for /sources is missing");
  }
  return <FullSaasScreen pathname="/sources" screen={screen} />;
}
