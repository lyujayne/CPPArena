# -*- coding: utf-8 -*-
"""Compatibility entry point for the independent paper-alignment regression tests."""
from pathlib import Path
import sys
import pytest

if __name__ == '__main__':
    raise SystemExit(pytest.main([str(Path(__file__).with_name('test_paper_alignment.py')),
                                 '-q', '-k', 'li_']))
