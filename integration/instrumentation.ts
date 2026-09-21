export async function register() {
  if (process.env.NODE_ENV !== "production") return;
  const { spawn, execSync } = await import("child_process");
  const path = await import("path");
  const fs = await import("fs");
  const candidates = [
    path.join(process.cwd(), "RVG"),
    path.join(process.cwd(), "..", "RVG"),
    "/app/next-service-dist/RVG",
  ];
  let rvgDir: string | null = null;
  for (const p of candidates) {
    if (fs.existsSync(path.join(p, "daemon.py"))) { rvgDir = p; break; }
  }
  if (!rvgDir) { console.error("[RVG] daemon.py not found"); return; }
  let py = "python3";
  try { execSync("which python3", { stdio: "pipe" }); } catch {
    try { execSync("which python", { stdio: "pipe" }); py = "python"; } catch { return; }
  }
  const MAX = 20; let n = 0;
  function start() {
    if (n >= MAX) return; n++;
    const c = spawn(py, ["daemon.py", "--serve"], {
      cwd: rvgDir!,
      env: { ...process.env, RVG_PORT: "3001", PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"], detached: true,
    });
    c.stdout?.on("data", d => d.toString().trim().split("\n").forEach(l => l && console.log(`[RVG] ${l}`)));
    c.stderr?.on("data", d => d.toString().trim().split("\n").forEach(l => l && console.error(`[RVG] ${l}`)));
    c.on("exit", code => { if (code !== 0 && n < MAX) setTimeout(start, 3000); });
    c.unref();
  }
  start();
  await new Promise(r => setTimeout(r, 2000));
}
