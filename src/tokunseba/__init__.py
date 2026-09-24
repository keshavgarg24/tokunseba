"""tokunseba: one local proxy in front of every AI coding tool on this machine.

The command line is the usual way in (`tokunseba init`). For code that is not behind the
proxy, the same pipeline is three functions -- see `tokunseba.api`.
"""
from .api import Change, Result, compress, expand, shrink

__version__ = "0.1.1"

__all__ = ["Change", "Result", "__version__", "compress", "expand", "shrink"]
