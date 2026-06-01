"""Root conftest — adds the project root to sys.path so 'app.*' imports work."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
