/**
 * Next.js Instrumentation — spawns RVG Python app on port 3001 in production.
 * Caddy proxies :81 → :3001. Next.js stays on :3000 (unused, health check only).
 */

export async function register() {
  if (process.env.NODE_ENV !== 'production') return;

  const { spawn, execSync } = await import('child_process');
  const path = await import('path');
  const fs = await import('fs');

  console.log('[instrumentation] Starting RVG Python app...');

  // Find RVG directory
  const candidates = [
    path.join(process.cwd(), 'RVG'),
    path.join(process.cwd(), '..', 'RVG'),
    '/app/next-service-dist/RVG',
  ];

  let rvgDir: string | null = null;
  for (const p of candidates) {
    if (fs.existsSync(path.join(p, 'daemon.py'))) {
      rvgDir = p;
      break;
    }
  }

  if (!rvgDir) {
    console.error('[instrumentation] RVG/daemon.py not found. Tried:', candidates);
    return;
  }

  // Find Python
  let pythonBin: string | null = null;
  for (const bin of ['python3', 'python', '/usr/bin/python3']) {
    try {
      execSync(`which ${bin}`, { stdio: 'pipe' });
      pythonBin = bin;
      break;
    } catch {}
  }

  if (!pythonBin) {
    console.error('[instrumentation] Python not found');
    return;
  }

  // Spawn with auto-restart
  const MAX_RESTARTS = 20;
  let restartCount = 0;

  function spawnRvg() {
    if (restartCount >= MAX_RESTARTS) return;
    restartCount++;

    const child = spawn(pythonBin!, ['daemon.py', '--serve'], {
      cwd: rvgDir!,
      env: {
        ...process.env,
        RVG_PORT: '3001',
        PYTHONUNBUFFERED: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: true,
    });

    child.stdout?.on('data', (d: Buffer) =>
      d.toString().trim().split('\n').forEach((l) => l && console.log(`[RVG] ${l}`))
    );
    child.stderr?.on('data', (d: Buffer) =>
      d.toString().trim().split('\n').forEach((l) => l && console.error(`[RVG] ${l}`))
    );

    child.on('exit', (code: number | null) => {
      if (code !== 0 && restartCount < MAX_RESTARTS) {
        setTimeout(spawnRvg, 3000);
      }
    });

    child.unref();
  }

  spawnRvg();
  await new Promise((r) => setTimeout(r, 2000));
}
