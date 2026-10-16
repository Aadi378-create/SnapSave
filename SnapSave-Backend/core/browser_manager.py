"""Browser ownership is local to the thread; no shared logged-in profile."""
import threading
import logging
from playwright.sync_api import sync_playwright
_local=threading.local()

def get_browser():
    if getattr(_local,"context",None) is None:
        try:
            _local.playwright=sync_playwright().start()
            _local.browser=_local.playwright.chromium.launch(headless=True)
            _local.context=_local.browser.new_context()
        except Exception:
            close_browser()
            raise
    return _local.context

def close_browser():
    resources=[(getattr(_local,"context",None),"close"),(getattr(_local,"browser",None),"close"),(getattr(_local,"playwright",None),"stop")]
    _local.context=None;_local.browser=None;_local.playwright=None
    for resource,method in resources:
        if resource is not None:
            try:
                getattr(resource,method)()
            except Exception:
                logging.warning("Browser resource cleanup failed",exc_info=True)
