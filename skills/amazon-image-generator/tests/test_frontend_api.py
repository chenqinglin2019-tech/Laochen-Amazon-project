from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "assets" / "codex-harness-app" / "web" / "app.js"


class FrontendApiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the browser API regression test")
    def test_invalid_success_envelopes_are_recoverable_errors(self):
        harness = r'''
const fs = require("fs");
const vm = require("vm");
global.window = {
  addEventListener() {},
  clearTimeout() {},
  setTimeout() {},
  location: { assign() {} },
  localStorage: { getItem() { return null; } }
};
global.document = {};
const source = fs.readFileSync(process.argv[2], "utf8") +
  "\nglobalThis.__testApi = api;";
vm.runInThisContext(source, { filename: process.argv[2] });

async function expectInvalid(jsonImpl) {
  global.fetch = async () => ({ status: 200, ok: true, json: jsonImpl });
  try {
    await global.__testApi("/api/bootstrap");
    throw new Error("expected invalid response to fail");
  } catch (error) {
    if (error.code !== "invalid_api_response") throw error;
    if (!error.message.includes("重新运行安装修复")) throw error;
  }
}

(async () => {
  await expectInvalid(async () => null);
  await expectInvalid(async () => { throw new SyntaxError("HTML is not JSON"); });
  global.fetch = async () => ({
    status: 200,
    ok: true,
    json: async () => ({ data: { token_configured: false }, requestId: "test" })
  });
  const data = await global.__testApi("/api/bootstrap");
  if (data.token_configured !== false) throw new Error("valid envelope was not returned");
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
'''
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as script:
            script.write(harness)
            script.flush()
            result = subprocess.run(
                [shutil.which("node"), script.name, str(APP_JS)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


class OptionShapeTests(unittest.TestCase):
    """Dropdowns display `name` and submit `value`; see references/api.md."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the option-shape test")
    def test_name_is_displayed_and_value_is_submitted(self):
        harness = r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
global.window = { addEventListener() {}, location: { assign() {} } };
global.document = {};
const source = fs.readFileSync(process.argv[2], "utf8") +
  "\nglobalThis.__pair = pair; globalThis.__modelName = modelName;";
vm.runInThisContext(source, { filename: process.argv[2] });

const pair = globalThis.__pair;
const modelName = globalThis.__modelName;

// The contract shape.
assert.deepStrictEqual(pair({ name: "英语", value: "en" }), { value: "en", label: "英语" });
// A plain string is both at once.
assert.deepStrictEqual(pair("1:1"), { value: "1:1", label: "1:1" });
// name wins over label for display; value is never replaced by name.
assert.deepStrictEqual(pair({ name: "干净白底", label: "clean", value: "clean" }),
  { value: "clean", label: "干净白底" });
// Older shapes still render rather than going blank.
assert.deepStrictEqual(pair({ label: "4:5", value: "4:5" }), { value: "4:5", label: "4:5" });
assert.deepStrictEqual(pair({ title: "2K", value: "2K" }), { value: "2K", label: "2K" });
// name alone is the only sane fallback for the wire value.
assert.deepStrictEqual(pair({ name: "en" }), { value: "en", label: "en" });
// Falsy-but-real values survive.
assert.deepStrictEqual(pair({ name: "零", value: 0 }), { value: "0", label: "零" });
// Models follow the same rule.
assert.strictEqual(modelName({ name: "香蕉 2 代", value: "1|nano-banana-2" }), "香蕉 2 代");
assert.strictEqual(modelName({ label: "Nano Banana", value: "1|nano-banana" }), "Nano Banana");
assert.strictEqual(modelName({ value: "1|only-value" }), "1|only-value");
'''
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as script:
            script.write(harness)
            script.flush()
            result = subprocess.run(
                [shutil.which("node"), script.name, str(APP_JS)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
