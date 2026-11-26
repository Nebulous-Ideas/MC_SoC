"""Run the composition tools' own offline tests (compose/) as part of the repo test run."""
import os, sys, unittest

COMPOSE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "compose")


def load_tests(loader, tests, pattern):
    sys.path.insert(0, COMPOSE)
    suite = unittest.TestSuite()
    suite.addTests(loader.discover(COMPOSE, pattern="test_*.py", top_level_dir=COMPOSE))
    return suite
