import { Dashboard } from "./dashboard";

export const metadata = {
  title: "pbot control room",
  description: "Local control and progress tracking for Pocket Bot.",
};

export default function Home() {
  return <Dashboard />;
}
