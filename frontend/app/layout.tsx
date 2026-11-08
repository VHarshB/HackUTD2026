import "./globals.css";
export const metadata = {
  title: "NightShift AI | Oilfield Digital Twin",
  description:
    "An interactive 3D digital twin for oilfield water operations, recorded telemetry, and verified response planning.",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
