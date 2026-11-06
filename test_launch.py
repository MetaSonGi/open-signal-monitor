import sys
import unittest
from unittest.mock import patch
from launch import APPS,main

class LauncherTests(unittest.TestCase):
    def test_routes_use_existing_modules_and_restore_arguments(self):
        original=sys.argv
        for role,(module,_) in APPS.items():
            with self.subTest(role=role),patch('launch.runpy.run_module') as run:
                def inspect(name,run_name):
                    self.assertEqual(sys.argv,[module])
                    self.assertEqual((name,run_name),(module,'__main__'))
                run.side_effect=inspect
                main([role])
                run.assert_called_once()
                self.assertIs(sys.argv,original)
    def test_list_never_starts_an_app(self):
        with patch('launch.runpy.run_module') as run,patch('builtins.print'):
            main(['--list'])
            run.assert_not_called()
    def test_failure_restores_arguments(self):
        original=sys.argv
        with patch('launch.runpy.run_module',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):main(['web'])
        self.assertIs(sys.argv,original)
if __name__=='__main__':unittest.main()
