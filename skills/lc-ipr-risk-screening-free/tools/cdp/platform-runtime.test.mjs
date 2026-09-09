import test from "node:test";
import path from "node:path";
import assert from "node:assert/strict";
import { chromeCandidates, resolveChromeExecutable, requireChromeExecutable, resolvePythonExecutable, expandUserPath } from "./platform-runtime.mjs";

test("Mac uses system then current-user Chrome without sender paths", () => {
  assert.deepEqual(chromeCandidates({platform:"darwin",env:{},home:path.posix.join("/", "Users", "测试 user")}), [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    path.posix.join("/", "Users", "测试 user", "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
  ]);
});
test("Windows checks system and per-user Chrome locations", () => {
  const home=path.win32.join("C:\\", "Users", "测试 user");
  const local=path.win32.join(home, "AppData", "Local");
  const paths=chromeCandidates({platform:"win32",env:{PROGRAMFILES:"C:\\Program Files",LOCALAPPDATA:local},home});
  assert.deepEqual(paths,["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",path.win32.join(local,"Google/Chrome/Application/chrome.exe")]);
});
test("explicit Chrome override remains authoritative, even if missing", () => {
  const options={platform:"darwin",env:{LC_IPR_CHROME:"/missing/chrome"},configured:"/configured/chrome",exists:x=>x==="/configured/chrome"};
  assert.equal(resolveChromeExecutable(options),null);
  assert.throws(()=>requireChromeExecutable(options),/CHROME_EXECUTABLE_UNAVAILABLE/);
});
test("tilde paths use Windows and POSIX separators safely", () => {
  const home=path.win32.join("C:\\", "Users", "me");
  assert.equal(expandUserPath("~\\folder x",{platform:"win32",home,cwd:"C:\\"}),path.win32.join(home,"folder x"));
  assert.equal(expandUserPath("~/folder x",{platform:"darwin",home:path.posix.join("/", "Users", "me")}),path.posix.join("/", "Users", "me", "folder x"));
});
test("scheduler interpreter remains exact and is not probed or replaced", () => {
  assert.equal(resolvePythonExecutable({env:{LC_IPR_PYTHON:"C:\\用户 data\\python.exe"},platform:"win32",probe:()=>{throw Error("must not probe")}}),"C:\\用户 data\\python.exe");
});
test("local venv is preferred without relying on python aliases", () => {
  const command=resolvePythonExecutable({env:{},platform:"win32",skillDir:"fixture-root",exists:p=>/Scripts[\\/]python\.exe$/.test(p),probe:()=>{throw Error("must not probe")}});
  assert.match(command,/\.venv.*Scripts[\\/]python\.exe$/);
});
test("Windows selects installed python instead of assuming python3", () => {
  const calls=[];
  const command=resolvePythonExecutable({env:{},platform:"win32",exists:()=>false,probe:name=>{calls.push(name);return {status:0,stdout:"3.12\n"}}});
  assert.equal(command,"python");assert.deepEqual(calls,["python"]);
});
test("Mac prefers actual 3.12+ and retains older historical interpreter fallback", () => {
  const args={env:{},platform:"darwin",exists:()=>false,probe:name=>name==="python3.12"?{status:0,stdout:"3.12\n"}:{status:1,stdout:""}};
  assert.equal(resolvePythonExecutable(args),"python3.12");
  assert.equal(resolvePythonExecutable({...args,probe:name=>name==="python3"?{status:0,stdout:"3.9\n"}:{status:1,stdout:""}}),"python3");
});
