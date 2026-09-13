"""Compatibility entry point; one implementation, no monkey-patching."""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('start_mega_brain.py')), run_name='__main__')
