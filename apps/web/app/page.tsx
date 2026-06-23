import FullSaasScreen from "./components/FullSaasScreen";
import { loadStandaloneScreen } from "../lib/standalone-screen";

export default function HomePage() {
  const screen = loadStandaloneScreen("/");
  if (!screen) {
    throw new Error("standalone screen for / is missing");
  }
  return <FullSaasScreen pathname="/" screen={screen} />;
}
