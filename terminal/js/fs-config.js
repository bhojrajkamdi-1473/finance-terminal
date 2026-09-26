/* FINSIGHT config — the ONLY frontend configuration.
   No secrets here, ever. AI/provider keys live server-side.
   To point at a dev backend: window.FINSIGHT_API_BASE = "http://localhost:8000";
   before other scripts load. Same-origin ("") by default. */
window.FINSIGHT = window.FINSIGHT || {};
if (typeof window.FINSIGHT.API_BASE !== "string") window.FINSIGHT.API_BASE = "";
