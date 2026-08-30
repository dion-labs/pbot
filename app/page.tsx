import { Dashboard } from "./dashboard";

export const metadata = {
  title: "pbot — Pocket Bot control room",
  description: "Local Android automation and durable progress tracking for Pocket Bot.",
};

export default function Home() {
  return <Dashboard />;
}
