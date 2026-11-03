import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` -> http://localhost:5173 (API calls are forwarded to the backend on :8000)
// `npm run build` -> dist/ (served by the backend at http://127.0.0.1:8000)
export default defineConfig({
  base: "/staff/",  // dashboard lives at /staff - the public website is at /
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
