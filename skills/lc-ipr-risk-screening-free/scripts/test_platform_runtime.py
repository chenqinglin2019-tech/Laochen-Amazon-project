"""Pure platform matrix tests, not evidence of native Windows/Intel execution."""
import unittest
from unittest.mock import patch
import platform_runtime as runtime


class PlatformRuntimeTests(unittest.TestCase):
    def test_supported_mac_modes_are_explicit_and_unvalidated(self):
        for host, process, mode in (("arm64", "arm64", "none"), ("x64", "x64", "none"), ("arm64", "x64", "rosetta")):
            row = runtime.classify_platform(system="Darwin", os_version="14.7", host_arch=host,
                process_arch=process, process_bits=64, translation=mode)
            self.assertTrue(row["compatible"])
            self.assertEqual(row["translation"], mode)
            self.assertEqual(row["native_validation"], "not_run")
            self.assertIn("arm64" if process == "arm64" else "amd64", row["auth_binary_name"])

    def test_mac_older_unknown_and_conflicting_architecture_rejected(self):
        for version, host, process, mode in (("13.7", "x64", "x64", "none"), ("", "arm64", "arm64", "none"),
                ("15.0", "arm64", "x64", "none"), ("14.0", "unknown", "unknown", "none")):
            row = runtime.classify_platform(system="Darwin", os_version=version, host_arch=host,
                process_arch=process, process_bits=64, translation=mode)
            self.assertFalse(row["compatible"])
            self.assertIsNone(row["auth_binary_name"])

    def test_windows_exact_build_matrix(self):
        for build, release in ((19045, "10 22H2"), (26100, "11 24H2"), (26200, "11 25H2")):
            row = runtime.classify_platform(system="Windows", os_version=f"10.0.{build}", os_build=build,
                host_arch="x64", process_arch="x64", process_bits=64)
            self.assertTrue(row["compatible"])
            self.assertEqual(row["windows_release"], release)
            self.assertEqual(row["native_validation"], "not_run")

    def test_windows_arm_emulation_32bit_and_unknown_are_not_x64(self):
        cases = [("arm64", "arm64", 64, "none", 26100), ("arm64", "x64", 64, "emulated", 26100),
                 ("x64", "x86", 32, "emulated", 19045), ("x86", "x86", 32, "none", 19045),
                 ("unknown", "unknown", 64, "unknown", 26100), ("x64", "x64", 64, "none", 22631)]
        for host, process, bits, mode, build in cases:
            row = runtime.classify_platform(system="Windows", host_arch=host, process_arch=process,
                process_bits=bits, translation=mode, os_build=build)
            self.assertFalse(row["compatible"])
            self.assertIsNone(row["auth_binary_name"])

    def test_linux_has_no_full_workflow_claim(self):
        self.assertFalse(runtime.classify_platform(system="Linux", host_arch="x64", process_arch="x64", process_bits=64)["compatible"])

    def test_rosetta_detection_preserves_host_and_process(self):
        with patch.object(runtime.platform, "system", return_value="Darwin"), \
             patch.object(runtime.platform, "machine", return_value="x86_64"), \
             patch.object(runtime.platform, "mac_ver", return_value=("14.6", (), "")), \
             patch.object(runtime, "_sysctl", side_effect=lambda name: "1"):
            row = runtime.inspect_platform()
        self.assertEqual((row["host_arch"], row["process_arch"], row["translation"]), ("arm64", "x64", "rosetta"))


if __name__ == "__main__":
    unittest.main()
