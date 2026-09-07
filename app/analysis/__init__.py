"""
Analysis routines that are pure functions over data, with no framework
dependencies — importable by the API, the Streamlit dashboard and the tests
alike.
"""
from app.analysis.cusum import (
    CusumFault,
    CusumPoint,
    CusumResult,
    cusum,
    multichannel_cusum,
)

__all__ = [
    "CusumFault",
    "CusumPoint",
    "CusumResult",
    "cusum",
    "multichannel_cusum",
]
