"""Regression for cmd.exe's quoting contract when launching Provengo BAT."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.relationship_execution import native, windows_batch_command


class WindowsNativeLaunchTests(unittest.TestCase):
    def test_program_files_bat_uses_raw_double_wrapped_command(self):
        command = windows_batch_command([
            r'C:\Program Files\Provengo\Provengo Cli\provengo.BAT',
            'sample', '--size', '3', r'C:\work\temp\project with spaces'])
        self.assertIsInstance(command, str)
        self.assertEqual(command, 'cmd.exe /d /s /v:off /c ""C:\\Program Files\\Provengo\\Provengo Cli\\provengo.BAT" "sample" "--size" "3" "C:\\work\\temp\\project with spaces""')
        self.assertNotIn('\\"', command)

    def test_native_passes_raw_string_to_subprocess_on_windows(self):
        with patch('tools.relationship_execution.os.name', 'nt'), \
             patch('tools.relationship_execution.shutil.which', return_value=r'C:\Program Files\Provengo\provengo.BAT'), \
             patch('tools.relationship_execution.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
            native(['sample', '--size', '3'], 'C:\\work\\temp\\pilot')
        args = run.call_args.args[0]
        self.assertIsInstance(args, str)
        self.assertIn('/c ""C:\\Program Files', args)
        self.assertNotIn('\\"', args)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_non_windows_entrypoint_retains_argument_list(self):
        with patch('tools.relationship_execution.os.name', 'posix'), \
             patch('tools.relationship_execution.shutil.which', return_value='/usr/bin/provengo'), \
             patch('tools.relationship_execution.subprocess.run') as run:
            native(['sample'], '/workspace/model')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/provengo', 'sample', '/workspace/model'])

    def test_separators_are_inside_quotes_and_unsupported_arguments_rejected(self):
        self.assertIn('"C:\\work\\A&B"', windows_batch_command(['provengo.bat', r'C:\work\A&B']))
        for value in ('broken"path', 'line\nbreak', '%TEMP%'):
            with self.assertRaises(ValueError):
                windows_batch_command(['provengo.bat', value])


if __name__ == '__main__':
    unittest.main()
