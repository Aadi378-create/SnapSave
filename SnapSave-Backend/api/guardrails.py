"""Bound request size and write rates without storing customer content."""
import time
import os
import json
import logging
import threading
import asyncio
from collections import defaultdict, deque
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class RequestLimits(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.requests = defaultdict(deque)
        self.lock = threading.Lock()

    async def dispatch(self, request, call_next):
        started=time.perf_counter()
        def reject(detail,status):
            response=JSONResponse({'detail':detail},status_code=status)
            if status==429:response.headers['Retry-After']='60'
            return secure(response)

        def secure(response):
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['X-Frame-Options']='DENY'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['Cache-Control']='no-store'
            if os.getenv('ENABLE_REQUEST_TIMING','false').lower()=='true':
                elapsed=round((time.perf_counter()-started)*1000,2)
                response.headers['Server-Timing']=f'app;dur={elapsed}'
                route=getattr(request.scope.get('route'),'path','<unmatched>')
                logging.getLogger('uvicorn.error').info('SNAPSAVE_TIMING %s',json.dumps({'method':request.method,'route':route,'status':response.status_code,'duration_ms':elapsed}))
            return response

        # Limit before reading the body or running authentication/database work.
        mutation=request.method in {'POST','PUT','PATCH','DELETE'}
        batch=request.url.path=='/api/read-batch' and request.method=='POST'
        units=8 if batch else 1
        bucket='dev-auth' if request.url.path=='/api/auth/test-token' else 'write' if mutation and not batch else 'read'
        limit={'dev-auth':10,'write':120,'read':300}[bucket]
        key=(request.client.host if request.client else 'unknown',bucket)
        now=time.monotonic()
        with self.lock:
            if len(self.requests)>=10000:
                self.requests=defaultdict(deque,{k:v for k,v in self.requests.items() if v and v[-1]>now-60})
                if key not in self.requests and len(self.requests)>=10000:return reject('Too many requests. Try again shortly',429)
            queue=self.requests[key]
            while queue and queue[0]<=now-60:queue.popleft()
            if len(queue)+units>limit:return reject('Too many requests. Try again shortly',429)
            queue.extend([now]*units)
        if len(request.headers.get('authorization',''))>8192:return reject('Authorization header too large',431)
        if mutation:
            length=request.headers.get('content-length')
            if length is not None:
                if not length.isascii() or not length.isdigit():return reject('Invalid Content-Length',400)
                digits=length.lstrip('0') or '0'
                if len(digits)>5 or int(digits)>65536:return reject('Request exceeds 64 KB',413)
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        if len(body)+len(chunk)>65536:return reject('Request exceeds 64 KB',413)
                        body.extend(chunk)
            except TimeoutError:return reject('Request body timed out',408)
            request._body = bytes(body)
        return secure(await call_next(request))
