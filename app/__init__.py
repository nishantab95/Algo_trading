"""Application package.

Keep heavyweight trading bootstrap imports lazy so the read-only Discovery
surface can start without loading the inactive analysis and execution stack.
"""

__all__ = ["bootstrap_application"]


def bootstrap_application():
    from app.services.bootstrap_service import bootstrap_application as bootstrap

    return bootstrap()
