"""Bounded renderer IPC and public HTTPS request broker; no browser networking.

Only same-site GET dependencies are supported. Unsupported external resources
are reported rather than retried through a browser's unrestricted transport.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager, ExitStack
import json
import os
import re
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

from business_website_analysis import (WebsiteSafetyError, validate_target,
    public_address, website_tls_context, _remaining)

RESOURCE_BYTES = 2 * 1024 * 1024
TOTAL_BYTES = 8 * 1024 * 1024
_RENDER_SLOTS = threading.BoundedSemaphore(1)
MIMES = {
    'document': ('text/html',),
    'script': ('application/javascript', 'text/javascript', 'application/x-javascript'),
    'stylesheet': ('text/css',),
    'fetch': ('application/json', 'text/plain', 'text/html'),
    'xhr': ('application/json', 'text/plain', 'text/html'),
}

class RequestBroker:
    def __init__(self, source, deadline, *, resolve=socket.getaddrinfo):
        self.host = validate_target(source)[0]
        self.deadline = deadline
        self.resolve = resolve
        self.requests = 0
        self.total_bytes = 0

    def fetch(self, url, kind):
        import urllib3
        if kind not in MIMES:
            raise WebsiteSafetyError('Unsupported browser resource type')
        seen = set()
        for hop in range(6):
            remaining = _remaining(self.deadline)
            host, path, query = validate_target(url)
            # Stylesheets may live on a public CDN. They remain read-only, size-bounded
            # and MIME-checked through this broker; scripts, documents and data stay
            # same-site. Font, image and media requests are blocked by the worker.
            if host != self.host and kind != 'stylesheet':
                raise WebsiteSafetyError('Unsupported external-render dependency: '+host)
            if re.search(r'/(?:analytics|telemetry|tracking|payments?|checkout|gtag|gtm)(?:[/.]|$)',path,re.I):
                raise WebsiteSafetyError('Unnecessary tracking or payment dependency blocked')
            if url in seen:
                raise WebsiteSafetyError('Browser dependency redirect loop')
            seen.add(url)
            self.requests += 1
            if self.requests > 64:
                raise WebsiteSafetyError('Browser request limit exceeded')
            ip = public_address(host, self.resolve)
            remaining = _remaining(self.deadline)
            pool = urllib3.HTTPSConnectionPool(ip, port=443, assert_hostname=host,
                server_hostname=host, ssl_context=website_tls_context(), retries=False,
                timeout=urllib3.Timeout(total=remaining, connect=min(5,remaining),read=min(5,remaining)),
                maxsize=1, block=True)
            response = None
            try:
                response = pool.urlopen('GET',path+('?' + query if query else ''),
                    headers={'Host':host,'Accept':', '.join(MIMES[kind]),
                             'Accept-Encoding':'identity','User-Agent':'Growthrova-Research/1.0'},
                    redirect=False,preload_content=False)
                _remaining(self.deadline)
                if response.status in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location or hop==5:
                        raise WebsiteSafetyError('Browser dependency redirect limit exceeded')
                    url=urllib.parse.urljoin(url,location)
                    continue # Every hop repeats URL, DNS, TLS and size policy.
                if response.status != 200:
                    raise WebsiteSafetyError('Browser dependency did not return reviewable content')
                if response.headers.get('Content-Encoding','identity').strip().lower() not in ('','identity'):
                    raise WebsiteSafetyError('Unsupported compressed browser dependency')
                mime=response.headers.get('Content-Type','').split(';')[0].strip().lower()
                if mime not in MIMES[kind]:
                    raise WebsiteSafetyError('Unsupported browser dependency content type')
                length=response.headers.get('Content-Length')
                if length and int(length)>RESOURCE_BYTES:
                    raise WebsiteSafetyError('Browser resource byte limit exceeded')
                chunks=[]; size=0
                while True:
                    _remaining(self.deadline)
                    chunk=response.read1(65536,decode_content=False)
                    if not chunk:break
                    size+=len(chunk); self.total_bytes+=len(chunk)
                    if size>RESOURCE_BYTES or self.total_bytes>TOTAL_BYTES:
                        raise WebsiteSafetyError('Browser resource byte limit exceeded')
                    chunks.append(chunk)
                return {'url':url,'mime':mime,'body':b''.join(chunks)}
            except (OSError,ValueError,urllib3.exceptions.HTTPError) as exc:
                if isinstance(exc,WebsiteSafetyError):raise
                raise WebsiteSafetyError('Browser dependency could not be fetched safely') from exc
            finally:
                if response is not None:
                    response.close();response.release_conn()
                pool.close()
        raise WebsiteSafetyError('Browser dependency redirect limit exceeded')


@contextmanager
def deny_all_proxy():
    """An actual local denial listener, never a possibly occupied fixed port."""
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    stopped=threading.Event();thread=None
    try:
        listener.bind(('127.0.0.1',0));listener.listen(8);listener.settimeout(.1)
        def deny():
            while not stopped.is_set():
                try:connection,_=listener.accept()
                except socket.timeout:continue
                except OSError:break
                with connection:
                    connection.settimeout(.1)
                    try:
                        connection.recv(4096)
                        connection.sendall(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                    except OSError:pass
        thread=threading.Thread(target=deny,daemon=True,name='growthrova-render-deny-proxy')
        thread.start()
        yield 'http://127.0.0.1:'+str(listener.getsockname()[1])
    finally:
        stopped.set();listener.close()
        if thread:thread.join(timeout=.3)


def renderer_environment(directory, cache=None):
    """Never inherit app credentials, proxy settings, Python paths or owner HOME."""
    env={'PATH':'/usr/bin:/bin','HOME':directory,'TMPDIR':directory,
         'LANG':'C.UTF-8','PYTHONIOENCODING':'utf-8'}
    if cache:env['PLAYWRIGHT_BROWSERS_PATH']=cache
    return env


def _reap_renderer(process):
    try:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=3)
    finally:
        process.stdin.close();process.stdout.close()


def render_website(source, *, deadline=None):
    deadline=min(deadline or time.monotonic()+20,time.monotonic()+20)
    executable=os.environ.get('GROWTHROVA_RESEARCH_RENDER_PYTHON',sys.executable)
    cache=os.environ.get('GROWTHROVA_RESEARCH_BROWSER_CACHE')
    browser=os.environ.get('GROWTHROVA_RESEARCH_BROWSER_EXECUTABLE')
    for path in (executable,cache,browser):
        if path and (not os.path.isabs(path) or not Path(path).exists()):
            raise WebsiteSafetyError('JavaScript renderer runtime is not configured correctly')
    validate_target(source)
    if not _RENDER_SLOTS.acquire(blocking=False):
        raise WebsiteSafetyError('JavaScript renderer busy; retry shortly')
    process=None; timer=None
    try:
        with (tempfile.TemporaryDirectory(prefix='growthrova-research-') as directory,
              deny_all_proxy() as proxy, ExitStack() as cleanup):
            worker=Path(__file__).with_name('business_website_browser_worker.py')
            process=subprocess.Popen([executable,'-I',str(worker)],cwd=directory,
                env=renderer_environment(directory,cache),stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,
                bufsize=0)
            cleanup.callback(_reap_renderer,process) # Before proxy/profile teardown, including successful snapshots.
            def stop():
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            timer=threading.Timer(_remaining(deadline),stop);timer.daemon=True;timer.start()
            broker=RequestBroker(source,deadline)
            def send(value):
                process.stdin.write((json.dumps(value)+'\n').encode());process.stdin.flush()
            send({'url':source,'browser':browser,'proxy':proxy,'timeout_ms':int(_remaining(deadline)*1000)})
            blocked=[];buffer=b'';messages=0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                while True:
                    if not selector.select(_remaining(deadline)):
                        raise WebsiteSafetyError('JavaScript renderer deadline exceeded')
                    chunk=os.read(process.stdout.fileno(),65536)
                    if not chunk:raise WebsiteSafetyError('JavaScript renderer unavailable or failed')
                    buffer+=chunk
                    if len(buffer)>1024*1024:raise WebsiteSafetyError('JavaScript renderer output limit exceeded')
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1);messages+=1
                        if messages>96:raise WebsiteSafetyError('JavaScript renderer request limit exceeded')
                        message=json.loads(line)
                        if message.get('type')=='request':
                            try:
                                resource=broker.fetch(message.get('url'),message.get('kind'))
                                send({'body':base64.b64encode(resource['body']).decode(),'mime':resource['mime']})
                            except WebsiteSafetyError as exc:
                                reason=str(exc)[:180]
                                if reason not in blocked and len(blocked)<12:blocked.append(reason)
                                send({'error':reason})
                        elif message.get('type')=='result':
                            markup=message.get('html')
                            if not isinstance(markup,str) or len(markup.encode())>512*1024:
                                raise WebsiteSafetyError('Invalid JavaScript renderer result')
                            identity=message.get('visual_identity')
                            if not isinstance(identity,dict):identity=None
                            return {'html':markup,'source_url':source,'blocked_dependencies':blocked,
                                    'request_count':broker.requests,'transferred_bytes':broker.total_bytes,
                                    **({'visual_identity':identity} if identity else {})}
                        else:
                            stage=message.get('stage')
                            reasons={'runtime_import':'JavaScript renderer requires Playwright in GROWTHROVA_RESEARCH_RENDER_PYTHON',
                                     'sandbox_launch':'Sandboxed Chromium could not start; check isolated renderer runtime and browser cache',
                                     'context_setup':'JavaScript renderer requires supported interception and isolation capabilities',
                                     'page_render':'JavaScript page could not render within the safe dependency policy'}
                            raise WebsiteSafetyError(reasons.get(stage,'JavaScript renderer unavailable or failed'))
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        if isinstance(exc,WebsiteSafetyError):raise
        raise WebsiteSafetyError('JavaScript renderer unavailable or failed') from exc
    finally:
        if timer:timer.cancel()
        _RENDER_SLOTS.release()
