"""Redirect, streaming-memory and caller deadline regressions at the real reader boundary."""
import itertools, threading, time, tracemalloc, unittest
from unittest.mock import patch
import business_website_analysis as website

DNS=[(2,1,6,'',('93.184.216.34',443))]
WORDS='Our workshop provides repair appointments. Contact the team to discuss the service.'
class Response:
 def __init__(self,status=200,headers=None,chunks=None):
  self.status=status;self.headers={'Content-Type':'text/html',**(headers or {})}
  self.chunks=iter(chunks if chunks is not None else [('<title>Workshop</title><p>'+WORDS+'</p>').encode()])
  self.closed=False;self.read_sizes=[]
 def read(self,n):
  self.read_sizes.append(n);return b''.join(self.chunks)[:n]
 def read1(self,n,**kwargs):
  self.read_sizes.append(n);return next(self.chunks,b'')
 def release_conn(self):self.closed=True
 def close(self):self.closed=True
class Pool:
 def __init__(self,response):self.response=response;self.closed=False
 def urlopen(self,*args,**kwargs):return self.response
 def close(self):self.closed=True

class WebsiteTransportRegressionTests(unittest.TestCase):
 def run_reader(self,responses,resolve=None,**kwargs):
  pools=[Pool(response) for response in responses]
  with patch('urllib3.HTTPSConnectionPool',side_effect=pools) as factory:
   result=website.extract_website('https://example.org/start',resolve=resolve or (lambda *a,**k:DNS),**kwargs)
  return result,pools,factory
 def test_relative_and_www_canonical_redirects_preserve_actual_source_and_revalidate_dns(self):
  seen=[]
  def resolve(host,*args,**kwargs):seen.append(host);return DNS
  responses=[Response(301,{'Location':'/next'}),Response(308,{'Location':'https://www.example.org/final'}),Response()]
  try:result,pools,factory=self.run_reader(responses,resolve)
  except website.WebsiteSafetyError as error:self.fail('Normal canonical redirects rejected: '+str(error))
  self.assertEqual(result['source_url'],'https://www.example.org/final')
  self.assertEqual(seen,['example.org','example.org','www.example.org'])
  self.assertEqual(result['observations']['visible_paragraphs'],[WORDS])
  self.assertTrue(all(pool.closed for pool in pools))
 def test_redirect_to_private_dns_never_opens_second_connection(self):
  calls=[]
  def resolve(host,*args,**kwargs):
   calls.append(host)
   return DNS if host=='example.org' else [(2,1,6,'',('127.0.0.1',443))]
  response=Response(302,{'Location':'https://internal.example.org/secret'})
  with patch('urllib3.HTTPSConnectionPool',return_value=Pool(response)) as factory:
   with self.assertRaises(website.WebsiteSafetyError):
    website.extract_website('https://example.org/start',resolve=resolve)
  self.assertEqual(calls,['example.org','internal.example.org'])
  self.assertEqual(factory.call_count,1)
 def test_unsafe_redirects_fail_before_connection_and_loops_are_bounded(self):
  for target in ['http://example.org/','https://user:pass@example.org/','https://127.0.0.1/']:
   with self.subTest(target=target),patch('urllib3.HTTPSConnectionPool',return_value=Pool(Response(302,{'Location':target}))) as factory:
    with self.assertRaises(website.WebsiteSafetyError):
     website.extract_website('https://example.org/',resolve=lambda *a,**k:DNS)
    self.assertEqual(factory.call_count,1)
  responses=[Response(302,{'Location':'/b'}),Response(302,{'Location':'/start'})]
  with patch('urllib3.HTTPSConnectionPool',side_effect=[Pool(r) for r in responses]) as factory:
   with self.assertRaises(website.WebsiteSafetyError):
    website.extract_website('https://example.org/start',resolve=lambda *a,**k:DNS)
   self.assertLessEqual(factory.call_count,2)
 def test_large_script_is_streamed_without_whole_body_buffer_and_late_text_survives(self):
  chunk=b'x'*65536
  response=Response(chunks=itertools.chain([b'<title>Workshop</title><script>'],itertools.repeat(chunk,512),[('</script><p>'+WORDS+'</p>').encode()]))
  tracemalloc.start()
  try:
   result,_,_=self.run_reader([response])
   _,peak=tracemalloc.get_traced_memory()
  finally:tracemalloc.stop()
  self.assertEqual(result['observations']['visible_paragraphs'],[WORDS])
  self.assertLessEqual(max(response.read_sizes),65536,'Reader requested an entire page at once')
  self.assertLess(peak,8*1024*1024,'Streaming retained a large script or whole decoded page')
 def test_chunk_boundaries_preserve_utf8_and_text_words(self):
  body=('<title>Café workshop</title><p>Café repairs and inspections are available by appointment.</p>').encode()
  response=Response(chunks=[body[i:i+1] for i in range(len(body))])
  result,_,_=self.run_reader([response])
  self.assertEqual(result['observations']['title'],'Café workshop')
  self.assertEqual(result['observations']['visible_paragraphs'],['Café repairs and inspections are available by appointment.'])
 def test_overall_deadline_includes_blocked_dns_and_releases_caller(self):
  release=threading.Event()
  def slow_dns(*args,**kwargs):release.wait(2);return DNS
  started=time.monotonic()
  try:
   try:
    with self.assertRaisesRegex(website.WebsiteSafetyError,'deadline'):
     website.extract_website('https://example.org/',resolve=slow_dns,timeout_seconds=.1)
   except TypeError as error:self.fail('Reader lacks an overall caller deadline: '+str(error))
   self.assertLess(time.monotonic()-started,.5)
  finally:release.set()
 def test_slow_stream_cannot_extend_overall_deadline(self):
  def chunks():
   for _ in range(100):
    time.sleep(.03);yield b'<p>Our workshop offers repairs by appointment.</p>'
  response=Response(chunks=chunks());started=time.monotonic()
  try:
   with self.assertRaisesRegex(website.WebsiteSafetyError,'deadline'):
    self.run_reader([response],timeout_seconds=.1)
  except TypeError as error:self.fail('Reader lacks an overall stream deadline: '+str(error))
  self.assertLess(time.monotonic()-started,.5)
  # The bounded worker must observe its expired deadline and close transport.
  for _ in range(50):
   if response.closed:break
   time.sleep(.01)
  self.assertTrue(response.closed)

 def test_oversized_quoted_script_attribute_is_discarded_without_leaking_script_as_evidence(self):
  response=Response(chunks=itertools.chain([b"<script data-blob='"],itertools.repeat(b'x'*65535+b'>',512),[("'>var x='<p>Not a real business offer.</p>';</script><p>"+WORDS+"</p>").encode()]))
  tracemalloc.start()
  try:
   result,_,_=self.run_reader([response]);_,peak=tracemalloc.get_traced_memory()
  finally:tracemalloc.stop()
  self.assertEqual(result['observations']['visible_paragraphs'],[WORDS])
  self.assertLess(peak,8*1024*1024)
 def test_large_comment_does_not_retain_page_or_hide_following_business_text(self):
  response=Response(chunks=itertools.chain([b'<!--'],itertools.repeat(b'x'*65536,512),[('--><p>'+WORDS+'</p>').encode()]))
  tracemalloc.start()
  try:
   result,_,_=self.run_reader([response]);_,peak=tracemalloc.get_traced_memory()
  finally:tracemalloc.stop()
  self.assertEqual(result['observations']['visible_paragraphs'],[WORDS])
  self.assertLess(peak,8*1024*1024)
 def test_redirect_hops_are_limited_even_without_a_loop(self):
  pools=[Pool(Response(302,{'Location':'/hop-'+str(i)})) for i in range(6)]
  with patch('urllib3.HTTPSConnectionPool',side_effect=pools) as factory:
   with self.assertRaisesRegex(website.WebsiteSafetyError,'redirect limit'):
    website.extract_website('https://example.org/start',resolve=lambda *a,**k:DNS)
   self.assertEqual(factory.call_count,6)
   self.assertTrue(all(pool.closed for pool in pools))
