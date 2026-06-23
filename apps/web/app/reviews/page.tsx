import FullSaasScreen from "../components/FullSaasScreen";
import { loadStandaloneScreen } from "../../lib/standalone-screen";

export default function ReviewsPage() {
  const screen = loadStandaloneScreen("/reviews");
  if (!screen) {
    throw new Error("standalone screen for /reviews is missing");
  }
  return <FullSaasScreen pathname="/reviews" screen={screen} />;
}
