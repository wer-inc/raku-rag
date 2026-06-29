import FullSaasScreen from "../components/FullSaasScreen";
import { loadStandaloneScreen } from "../../lib/standalone-screen";

export default function FilesPage() {
  const screen = loadStandaloneScreen("/files");
  if (!screen) {
    throw new Error("standalone screen for /files is missing");
  }
  return <FullSaasScreen pathname="/files" screen={screen} />;
}
