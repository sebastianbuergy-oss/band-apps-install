"""Buergys Builds - Windows-first iOS build controller.

Standard library only on purpose: the controller must run on Sebastian's HP
with a plain Python install, without pip, without a build toolchain and
without any paid service.  Everything that genuinely needs macOS is pushed
behind the MacExecutor interface in :mod:`bb.executors`.
"""

__version__ = "0.1.0"
