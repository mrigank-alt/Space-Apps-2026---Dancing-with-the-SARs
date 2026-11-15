/** Frontend demo entry. The public page also runs without npm or a backend. */
export default function App() {
  return <iframe title="Groundsignal Rafsanjan simulation" src={`${import.meta.env.BASE_URL}rafsanjan-demo.html`} style={{ width: "100%", height: "100dvh", border: 0, display: "block" }} />;
}
