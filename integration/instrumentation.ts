/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * RVG Gateway bootstrap — production only.
 *
 * Starts the bundled Python gateway (RVG/daemon.py) on port 3001, next to
 * the Next.js server. The Caddyfile routes public traffic -> :3001.
 */

const RVG_PORT = "3001";

export async function register() {
  if (process.env.NODE_ENV !== "production") return;

  // ── Resolve node builtins without static imports ─────────────────────────
  const getBuiltin = (process as any).getBuiltinModule?.bind(process);
  if (!getBuiltin) {
    console.error("[RVG] process.getBuiltinModule unavailable — gateway not started");
    return;
  }
  const { spawn, execFileSync } = getBuiltin("child_process") as typeof import("child_process");
  const path = getBuiltin("path") as typeof import("path");
  const fs = getBuiltin("fs") as typeof import("fs");

  // ── Locate the RVG python app ─────────────────────────────────────────────
  // NOTE: bracket access on process keeps the bundler from flagging
  // process.cwd() in the (unused) edge-runtime bundle of this file.
  const cwd: string = (process as any)["cwd"]?.() ?? "";
  const candidates = [
    path.join(cwd, "RVG"),
    path.join(cwd, "..", "RVG"),
    "/app/next-service-dist/RVG",
  ];
  const rvgDir = candidates.find((p) => fs.existsSync(path.join(p, "daemon.py")));
  if (!rvgDir) {
    console.error("[RVG] daemon.py not found — looked in:", candidates.join(", "));
    return;
  }
  console.log(`[RVG] gateway dir: ${rvgDir}`);

  // ── Find a python interpreter ─────────────────────────────────────────────
  let py = "python3";
  try {
    execFileSync("which", ["python3"], { stdio: "pipe" });
  } catch {
    try {
      execFileSync("which", ["python"], { stdio: "pipe" });
      py = "python";
    } catch {
      console.error("[RVG] python not found in production image — gateway disabled");
      return;
    }
  }

  // ── Ensure python dependencies ────────────────────────────────────────────
  // The deploy pipeline (start.sh) exports PYTHONPATH pointing at the
  // platform-built python-runtime/site-packages (correct ABI for the FC
  // interpreter). Keep it FIRST and append our bundled vendor as fallback —
  // never clobber it, or ABI-mismatched wheels could break the import.
  const vendor = path.join(rvgDir, "vendor");
  const mergedPath = [process.env.PYTHONPATH, vendor].filter(Boolean).join(":");
  const probeEnv = { ...process.env, PYTHONPATH: mergedPath };
  // NOTE: the redis client package is REQUIRED for the Redis persistence
  // backend. Images whose python runtime was built from an older
  // requirements.txt have fastapi/uvicorn but no `redis` — the panel would
  // boot with REDIS_URL set yet never connect (silent file fallback).
  const probeDeps = (): boolean => {
    try {
      execFileSync(py, ["-c", "import fastapi, uvicorn, redis.asyncio"], {
        env: probeEnv,
        stdio: "pipe",
        timeout: 30_000,
      });
      return true;
    } catch {
      return false;
    }
  };

  let hasDeps = probeDeps();
  if (hasDeps) {
    console.log("[RVG] python deps OK (fastapi, uvicorn, redis)");
  } else {
    console.log(
      "[RVG] deps incomplete — self-heal: pip install --target vendor redis ...",
    );
    // Fast path: install ONLY the missing redis client into the bundled
    // vendor dir (no root needed, small wheel). The daemon additionally
    // self-heals at boot, so this is belt-and-suspenders.
    const vendorPip: string[][] = [
      ["-m", "pip", "install", "--quiet", "--target", vendor, "redis>=5.0.1"],
      [
        "-m", "pip", "install", "--quiet", "--break-system-packages",
        "--target", vendor, "redis>=5.0.1",
      ],
    ];
    for (const args of vendorPip) {
      try {
        execFileSync(py, args, {
          env: probeEnv,
          stdio: "pipe",
          timeout: 180_000,
        });
        break;
      } catch {
        /* try next variant */
      }
    }
    hasDeps = probeDeps();
  }

  if (!hasDeps) {
    const attempts: string[][] = [
      ["-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
      ["-m", "pip", "install", "--quiet", "--break-system-packages", "-r", "requirements.txt"],
    ];
    for (const args of attempts) {
      try {
        execFileSync(py, args, { cwd: rvgDir, stdio: "pipe", timeout: 180_000 });
        hasDeps = true;
        console.log("[RVG] pip install succeeded");
        break;
      } catch (e) {
        console.error(`[RVG] pip install failed: ${(e as Error).message}`);
      }
    }
    hasDeps = probeDeps();
    if (!hasDeps)
      console.error("[RVG] continuing without verified deps — daemon may fail");
  }

  // ── Restore exec bits on the bundled redis binaries ────────────────────
  // Some deploy pipelines (zip/tar copy) strip the executable bit; without
  // it the daemon cannot boot its local Redis and silently falls back to
  // file storage (panel shows "Redis: disconnected").
  for (const bin of ["bin/redis-server", "bin/redis-cli"]) {
    const p = path.join(rvgDir, bin);
    if (!fs.existsSync(p)) continue;
    try {
      fs.accessSync(p, fs.constants.X_OK);
    } catch {
      try {
        fs.chmodSync(p, 0o755);
        console.log(`[RVG] restored exec bit: ${p}`);
      } catch {
        console.error(`[RVG] could not chmod ${p} — daemon will retry`);
      }
    }
  }

  // ── Spawn the gateway (auto-restart up to 20 times) ───────────────────────
  const MAX = 20;
  let n = 0;
  const start = () => {
    if (n >= MAX) {
      console.error("[RVG] gateway keeps crashing — giving up after 20 restarts");
      return;
    }
    n++;
    const c = spawn(py, ["daemon.py", "--serve"], {
      cwd: rvgDir,
      env: {
        ...process.env,
        RVG_PORT,
        DATA_DIR: path.join(rvgDir, "data"),
        PYTHONPATH: mergedPath,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    c.stdout?.on("data", (d) =>
      d.toString().trim().split("\n").forEach((l) => l && console.log(`[RVG] ${l}`)),
    );
    c.stderr?.on("data", (d) =>
      d.toString().trim().split("\n").forEach((l) => l && console.error(`[RVG] ${l}`)),
    );
    c.on("exit", (code) => {
      if (n < MAX) {
        console.error(`[RVG] gateway exited (code ${code}) — restart #${n} in 3s`);
        setTimeout(start, 3000);
      }
    });
    c.unref();
  };
  start();

  // Give uvicorn a moment to bind before the platform health-checks us.
  await new Promise((r) => setTimeout(r, 2000));
}
