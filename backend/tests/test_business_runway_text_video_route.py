import unittest
from unittest.mock import patch
import business_runway as runway
class DedicatedTextVideoEndpointTests(unittest.TestCase):
 def test_text_model_uses_specific_endpoint_without_paid_request(self):
  client=object.__new__(runway.RunwayClient)
  payload={'model':'gen4.5','duration':5,'ratio':'720:1280','promptText':'A realistic restaurant entrance with visible natural motion'}
  with patch.object(client,'_request',return_value={'id':'a'*36}) as get:
   self.assertEqual(client.submit_text_video(payload),{'id':'a'*36})
   get.assert_called_once_with('POST','/text_to_video',payload)
 def test_image_to_video_keeps_existing_route(self):
  client=object.__new__(runway.RunwayClient)
  req={'model':'gen4_turbo','duration':5,'ratio':'720:1280','promptImage':'data:image/jpeg;base64,aaa','promptText':'Natural camera movement'}
  with patch.object(client,'_request',return_value={'id':'b'*36}) as get:
   client.submit_video(req)
   get.assert_called_once_with('POST','/image_to_video',req)
 def test_mismatched_image_text_requests_rejected_before_network(self):
  client=object.__new__(runway.RunwayClient)
  with patch.object(client,'_request') as call:
   for request in ({'model':'gen4_turbo'},{'model':'gen4.5','promptImage':'secret'},None):
    with self.assertRaises(runway.RunwayError):client.submit_text_video(request)
   call.assert_not_called()
