/** Small dependency-free runtime selectors shared by CDP and its tests. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export function expandUserPath(value, { platform = process.platform, home = os.homedir(), cwd = process.cwd() } = {}) {
  const text = String(value || "");
  const paths = platform === "win32" ? path.win32 : path.posix;
  if (text === "~") return home;
  if (/^~[/\\]/.test(text)) return paths.join(home, text.slice(2));
  return paths.resolve(cwd, text);
}

export function chromeCandidates({ platform = process.platform, env = process.env, home = os.homedir(), configured = "" } = {}) {
  const explicit = env.LC_IPR_CHROME || env.CHROME_EXECUTABLE || configured;
  if (explicit) return [expandUserPath(explicit, { platform, home })];
  if (platform === "darwin") return [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    path.posix.join(home, "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
  ];
  if (platform === "win32") return [...new Set([
    env.PROGRAMFILES, env["PROGRAMFILES(X86)"], env.LOCALAPPDATA,
  ].filter(Boolean).map(root => path.win32.join(root, "Google/Chrome/Application/chrome.exe")))];
  // Retain existing Linux capability for old installations; full workflow
  // platform support is independently diagnosed by setup_skill.py.
  return ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
}

const isFile = value => { try { return fs.statSync(value).isFile(); } catch { return false; } };

export function resolveChromeExecutable(options = {}) {
  const exists = options.exists || isFile;
  return chromeCandidates(options).find(exists) || null;
}

export function requireChromeExecutable(options = {}) {
  const executable = resolveChromeExecutable(options);
  if (!executable) throw new Error("CHROME_EXECUTABLE_UNAVAILABLE: a detected system Chrome is required");
  return executable;
}

export function resolvePythonExecutable({ env = process.env, platform = process.platform, skillDir = SKILL_DIR,
  exists = isFile, probe = (command) => spawnSync(command, ["-c", "import sys;print('.'.join(map(str,sys.version_info[:2])))"],
    { encoding: "utf8", timeout: 5000, env: { ...env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" } }) } = {}) {
  // Explicit scheduler choice is authoritative. Let spawn report a bad explicit
  // executable rather than silently switching to a different environment.
  if (env.LC_IPR_PYTHON) return env.LC_IPR_PYTHON;
  const local = path.join(skillDir, ".venv", platform === "win32" ? "Scripts/python.exe" : "bin/python");
  if (exists(local)) return local;
  const commands = platform === "win32" ? ["python", "python3"] : ["python3.14", "python3.13", "python3.12", "python3", "python"];
  let legacy = null;
  for (const command of commands) {
    const result = probe(command);
    const match = /^([0-9]+)\.([0-9]+)\s*$/.exec(result.stdout || "");
    if (result.status !== 0 || !match || Number(match[1]) < 3) continue;
    if (Number(match[1]) > 3 || Number(match[2]) >= 12) return command;
    if (Number(match[2]) >= 9 && !legacy) legacy = command;
  }
  // Older supported historical inputs can still run; setup makes the new
  // installation's tested Python 3.12+ baseline explicit.
  return legacy || (platform === "win32" ? "python" : "python3");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const position = process.argv.indexOf("--chrome");
  const configured = position >= 0 ? process.argv[position + 1] || "" : "";
  const executable = resolveChromeExecutable({ configured });
  process.stdout.write(JSON.stringify({ status: executable ? "available" : "missing", path: executable,
    source: "local_runtime_detection", browser_launch: "not_run" }) + "\n");
}
