"""All browser transports are pinned and bounded, including redirect targets."""
import time, unittest
from unittest.mock import patch
from business_website_browser import RequestBroker, renderer_environment
from business_website_analysis import WebsiteSafetyError
from tests.test_business_website_transport import Response, Pool, DNS

class BrokerTests(unittest.TestCase):
 def broker(self,**kwargs):return RequestBroker('https://example.org/',time.monotonic()+5,**kwargs)
 def test_unsafe_subrequests_never_open_transport(self):
  for url in ['https://127.0.0.1/','http://example.org/','file:///etc/passwd','data:text/html,secret','https://u:p@example.org/','https://external.org/app.js']:
   with self.subTest(url=url),patch('urllib3.HTTPSConnectionPool') as pool:
    with self.assertRaises(WebsiteSafetyError):self.broker().fetch(url,'script')
    pool.assert_not_called()
 def test_private_mixed_and_rebound_dns_are_denied(self):
  private=(2,1,6,'',('127.0.0.1',443))
  for dns in [[private],DNS+[private]]:
   with patch('urllib3.HTTPSConnectionPool') as pool:
    with self.assertRaises(WebsiteSafetyError):self.broker(resolve=lambda *a,**k:dns).fetch('https://example.org/app.js','script')
    pool.assert_not_called()
 def test_tls_ip_pinning_and_no_browser_credentials(self):
  r=Response(headers={'Content-Type':'application/javascript'},chunks=[b'window.ready=true'])
  pool=Pool(r)
  with patch('urllib3.HTTPSConnectionPool',return_value=pool) as factory:
   result=self.broker(resolve=lambda *a,**k:DNS).fetch('https://example.org/app.js','script')
  self.assertEqual(result['body'],b'window.ready=true')
  self.assertEqual(factory.call_args.args[0],'93.184.216.34')
  self.assertEqual(factory.call_args.kwargs['server_hostname'],'example.org')
  self.assertTrue(factory.call_args.kwargs['ssl_context'].check_hostname)
  self.assertTrue(pool.closed)
 def test_redirect_private_dns_never_opens_second_connection(self):
  response=Response(302,{'Location':'https://sub.example.org/secret'})
  # Subdomains/external dependencies are unsupported; no direct browser fallback.
  with patch('urllib3.HTTPSConnectionPool',return_value=Pool(response)) as factory:
   with self.assertRaises(WebsiteSafetyError):self.broker(resolve=lambda *a,**k:DNS).fetch('https://example.org/app.js','script')
   self.assertEqual(factory.call_count,1)
 def test_same_host_redirect_revalidates_dns(self):
  resolve=unittest.mock.Mock(side_effect=[DNS,[(2,1,6,'',('10.0.0.1',443))]])
  with patch('urllib3.HTTPSConnectionPool',return_value=Pool(Response(302,{'Location':'/private'}))) as pool:
   with self.assertRaises(WebsiteSafetyError):self.broker(resolve=resolve).fetch('https://example.org/app.js','script')
   self.assertEqual(resolve.call_count,2);self.assertEqual(pool.call_count,1)
 def test_byte_and_request_limits_and_wrong_mime_are_enforced(self):
  for mime,body in [('application/javascript',b'a'*(2*1024*1024+1)),('image/png',b'PNG')]:
   with patch('urllib3.HTTPSConnectionPool',return_value=Pool(Response(headers={'Content-Type':mime},chunks=[body]))):
    with self.assertRaises(WebsiteSafetyError):self.broker(resolve=lambda *a,**k:DNS).fetch('https://example.org/app.js','script')
  broker=self.broker();broker.requests=64
  with self.assertRaises(WebsiteSafetyError):broker.fetch('https://example.org/a.js','script')
 def test_sanitized_environment_has_only_runtime_and_ephemeral_paths(self):
  with patch.dict('os.environ',{'GROWTHROVA_WRITER_API_KEY':'secret','AWS_SECRET_ACCESS_KEY':'secret','HOME':'/private','HTTP_PROXY':'http://unsafe'}):
   env=renderer_environment('/tmp/isolated','/opt/browser-cache')
  self.assertEqual(env['HOME'],'/tmp/isolated')
  self.assertEqual(env['PLAYWRIGHT_BROWSERS_PATH'],'/opt/browser-cache')
  self.assertFalse(any('KEY' in key or 'PROXY' in key for key in env))

class DenyProxyTests(unittest.TestCase):
 def test_proxy_explicitly_denies_connect_and_get_without_forwarding(self):
  import socket
  from business_website_browser import deny_all_proxy
  with deny_all_proxy() as address:
   host,port=address.removeprefix('http://').split(':')
   for request in [b'CONNECT localhost:22 HTTP/1.1\r\n\r\n',b'GET https://example.org/ HTTP/1.1\r\n\r\n']:
    with socket.create_connection((host,int(port)),timeout=1) as connection:
     connection.sendall(request)
     self.assertIn(b'403 Forbidden',connection.recv(512))

class BrokerBudgetTests(unittest.TestCase):
 def test_expired_deadline_opens_no_transport(self):
  with patch('urllib3.HTTPSConnectionPool') as pool:
   with self.assertRaisesRegex(WebsiteSafetyError,'deadline'):
    RequestBroker('https://example.org/',time.monotonic()-1).fetch('https://example.org/app.js','script')
   pool.assert_not_called()
 def test_total_byte_budget_cannot_be_reset_by_another_subrequest(self):
  broker=RequestBroker('https://example.org/',time.monotonic()+5,resolve=lambda *a,**k:DNS)
  broker.total_bytes=8*1024*1024
  with patch('urllib3.HTTPSConnectionPool',return_value=Pool(Response(headers={'Content-Type':'application/javascript'},chunks=[b'1']))):
   with self.assertRaisesRegex(WebsiteSafetyError,'byte limit'):broker.fetch('https://example.org/app.js','script')
 def test_redirect_loop_stops_and_closes_transports(self):
  broker=RequestBroker('https://example.org/',time.monotonic()+5,resolve=lambda *a,**k:DNS)
  pool=Pool(Response(302,{'Location':'/app.js'}))
  with patch('urllib3.HTTPSConnectionPool',return_value=pool) as factory:
   with self.assertRaisesRegex(WebsiteSafetyError,'redirect loop'):broker.fetch('https://example.org/app.js','script')
   self.assertEqual(factory.call_count,1);self.assertTrue(pool.closed)

class UnnecessaryDependencyTests(unittest.TestCase):
 def test_tracking_and_payment_dependencies_never_open_transport(self):
  for path in ['/analytics/collect','/tracking/pixel','/payments/create','/api/checkout/session','/gtag.js']:
   with self.subTest(path=path),patch('urllib3.HTTPSConnectionPool',return_value=Pool(Response())) as pool:
    with self.assertRaisesRegex(WebsiteSafetyError,'Unnecessary'):
     RequestBroker('https://example.org/',time.monotonic()+5,resolve=lambda *a,**k:DNS).fetch('https://example.org'+path,'fetch')
    pool.assert_not_called()

class RendererProcessTests(unittest.TestCase):
 def run_child(self,program,deadline):
  import subprocess, sys
  from contextlib import nullcontext
  from business_website_browser import render_website
  spawn=subprocess.Popen;children=[]
  def child(args,**kwargs):
   process=spawn([sys.executable,'-I','-c',program],**kwargs);children.append(process);return process
  with (patch('business_website_browser.deny_all_proxy',return_value=nullcontext('http://127.0.0.1:9')),
        patch('business_website_browser.subprocess.Popen',side_effect=child)):
   try:return render_website('https://example.org/',deadline=deadline)
   finally:
    self.assertTrue(children)
    self.assertIsNotNone(children[0].poll(),'Renderer child survived request cleanup')
 def test_nonresponsive_worker_is_killed_at_deadline(self):
  started=time.monotonic()
  with self.assertRaises(WebsiteSafetyError):
   self.run_child('import time;time.sleep(30)',time.monotonic()+.2)
  self.assertLess(time.monotonic()-started,2)
 def test_completed_worker_is_reaped_even_if_it_does_not_exit(self):
  program="import sys,json,time;sys.stdin.readline();print(json.dumps({'type':'result','html':'<h1>Real worker IPC</h1>'}),flush=True);time.sleep(30)"
  result=self.run_child(program,time.monotonic()+2)
  self.assertEqual(result['html'],'<h1>Real worker IPC</h1>')

class CompressedDependencyTests(unittest.TestCase):
 def test_unrequested_compressed_resource_is_denied_before_decompression(self):
  response=Response(headers={'Content-Type':'application/javascript','Content-Encoding':'gzip'},chunks=[b'compressed payload'])
  with patch('urllib3.HTTPSConnectionPool',return_value=Pool(response)):
   with self.assertRaisesRegex(WebsiteSafetyError,'compressed'):
    RequestBroker('https://example.org/',time.monotonic()+5,resolve=lambda *a,**k:DNS).fetch('https://example.org/app.js','script')
  self.assertEqual(response.read_sizes,[])

class RendererCleanupOrderTests(unittest.TestCase):
 def test_child_is_dead_before_its_private_profile_is_removed(self):
  import subprocess, sys, tempfile
  from contextlib import contextmanager, nullcontext
  from business_website_browser import render_website
  spawn=subprocess.Popen;directory_factory=tempfile.TemporaryDirectory;children=[]
  def child(args,**kwargs):
   code="import sys,json,time;sys.stdin.readline();print(json.dumps({'type':'result','html':'<p>IPC snapshot</p>'}),flush=True);time.sleep(30)"
   process=spawn([sys.executable,'-I','-c',code],**kwargs);children.append(process);return process
  @contextmanager
  def directory(**kwargs):
   with directory_factory(**kwargs) as path:
    yield path
    self.assertIsNotNone(children[0].poll(),'Live browser can still write while private profile is being removed')
  with (patch('business_website_browser.deny_all_proxy',return_value=nullcontext('http://127.0.0.1:9')),
        patch('business_website_browser.tempfile.TemporaryDirectory',side_effect=directory),
        patch('business_website_browser.subprocess.Popen',side_effect=child)):
   render_website('https://example.org/',deadline=time.monotonic()+2)
