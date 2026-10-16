"""Bound request size and write rates without storing customer content."""
import time
import threading
from collections import defaultdict, deque
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class RequestLimits(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.requests = defaultdict(deque)
        self.lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            body = bytearray()
            async for chunk in request.stream():
                if len(body)+len(chunk) > 65536:
                    return JSONResponse({"detail": "Request exceeds 64 KB"}, status_code=413)
                body.extend(chunk)
            request._body = bytes(body)
            key = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with self.lock:
                # Bounded map, no forwarded IP headers trusted here.
                if len(self.requests) >= 10000:
                    self.requests = defaultdict(deque, {k:v for k,v in self.requests.items() if v and v[-1] > now-60})
                    if key not in self.requests and len(self.requests)>=10000:
                        return JSONResponse({"detail":"Too many changes. Try again shortly"},status_code=429,headers={"Retry-After":"60"})
                queue = self.requests[key]
                while queue and queue[0] <= now-60:
                    queue.popleft()
                if len(queue) >= 120:
                    return JSONResponse({"detail": "Too many changes. Try again shortly"}, status_code=429, headers={"Retry-After":"60"})
                queue.append(now)
        return await call_next(request)
